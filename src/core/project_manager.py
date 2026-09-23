import os
import shutil
import time
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
from src.core.config import config, SystemConfig
from src.core.indexer import ProjectIndexer, ProjectIndexSummary, FileMetadata
from src.core.chunker import CodeChunk
from src.core.memory import LongTermMemoryManager, EpisodicMemory
from src.core.context_assembler import DynamicContextAssembler, DialogueTurn, AssembledContext
from src.core.llm_client import LocalLLMClient

class CodeModificationProposal(BaseModel):
    file_path: str
    action: str  # 'modify', 'create'
    code_content: str
    original_exists: bool

class ProjectManager:
    """
    Central controller managing project indexing, long-term memory lifecycle,
    and context assembly for local AI sessions.
    """
    def __init__(self, project_path: Optional[str] = None):
        self.project_path: Optional[Path] = Path(project_path).resolve() if project_path else None
        self.indexer = ProjectIndexer()
        self.memory_mgr: Optional[LongTermMemoryManager] = None
        self.assembler: Optional[DynamicContextAssembler] = None
        self.llm_client = LocalLLMClient()
        self.summary: Optional[ProjectIndexSummary] = None

        if self.project_path and self.project_path.exists():
            self._init_project(str(self.project_path))

    def _init_project(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        memory_dir = self.project_path / ".context_memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        db_path = memory_dir / "memory.db"
        self.memory_mgr = LongTermMemoryManager(str(db_path))
        self.assembler = DynamicContextAssembler(self.memory_mgr)

    def set_project(self, project_path: str) -> Dict[str, Any]:
        """Changes or initializes the target project directory."""
        self._init_project(project_path)
        # Check if project chunks are already saved in DB
        chunks, repo_map = self.memory_mgr.load_project_chunks()
        stats = self.memory_mgr.get_stats()
        if stats["total_chunks"] > 0:
            return {
                "project_path": str(self.project_path),
                "is_indexed": True,
                "stats": stats,
                "repo_map": repo_map
            }
        else:
            # Need indexing
            return self.index_project()

    def index_project(self) -> Dict[str, Any]:
        """Scans and indexes the current project into Long-Term Memory."""
        if not self.project_path or not self.project_path.exists():
            raise ValueError("No valid project path set")

        files_meta, chunks, repo_map = self.indexer.scan_project(str(self.project_path))
        self.memory_mgr.save_project_chunks(chunks, repo_map)

        total_tokens = sum(m.token_count for m in files_meta)
        total_lines = sum(m.line_count for m in files_meta)

        self.summary = ProjectIndexSummary(
            project_root=str(self.project_path),
            total_files=len(files_meta),
            total_chunks=len(chunks),
            total_tokens=total_tokens,
            total_lines=total_lines,
            repo_map=repo_map,
            files=files_meta
        )

        # Record indexing in episodic memory
        self.memory_mgr.add_episodic_memory(EpisodicMemory(
            session_id="system",
            memory_type="system_event",
            summary="Project Indexed",
            detail=f"Indexed {len(files_meta)} files ({len(chunks)} chunks, ~{total_tokens:,} tokens) in {self.project_path.name}",
            tags="index,setup"
        ))

        return {
            "project_path": str(self.project_path),
            "is_indexed": True,
            "stats": self.memory_mgr.get_stats(),
            "repo_map": repo_map,
            "total_files": len(files_meta),
            "total_chunks": len(chunks),
            "total_tokens": total_tokens
        }

    def prepare_context(
        self,
        prompt: str,
        dialogue_history: List[DialogueTurn],
        session_id: str = "default",
        custom_max_tokens: Optional[int] = None
    ) -> AssembledContext:
        """Assembles the tight, relevant context window for the user prompt."""
        if not self.assembler:
            raise ValueError("Project not initialized. Please select and index a project first.")
        return self.assembler.assemble(
            current_prompt=prompt,
            dialogue_history=dialogue_history,
            session_id=session_id,
            custom_max_tokens=custom_max_tokens
        )

    def record_turn(self, session_id: str, user_prompt: str, assistant_response: str):
        """Records dialogue turn and extracts potential decisions into Long-Term Memory."""
        if not self.memory_mgr:
            return

        # Record standard turn
        summary = user_prompt[:80] + ("..." if len(user_prompt) > 80 else "")
        self.memory_mgr.add_episodic_memory(EpisodicMemory(
            session_id=session_id,
            memory_type="turn",
            summary=f"User asked: {summary}",
            detail=f"Assistant answered ({len(assistant_response)} chars).",
            tags="conversation"
        ))

        # Check for decision/conclusion patterns
        decision_keywords = ["decided to", "agreed to", "설정함", "결정됨", "구현 완료", "수정함", "방식으로 변경"]
        for kw in decision_keywords:
            if kw in assistant_response.lower():
                self.memory_mgr.add_episodic_memory(EpisodicMemory(
                    session_id=session_id,
                    memory_type="decision",
                    summary=f"Decision noted: {kw}",
                    detail=assistant_response[:200],
                    tags="decision,architecture"
                ))
                break

    def extract_code_proposals(self, ai_response: str) -> List[CodeModificationProposal]:
        """
        Parses code blocks in AI response formatted as:
        ```python:path/to/file.py or ```path/to/file.py
        ...
        ```
        """
        if not self.project_path:
            return []

        pattern = re.compile(r'```(?:[a-zA-Z0-9_\-]+:)?([a-zA-Z0-9_\-/\\]+\.[a-zA-Z0-9]+)\n(.*?)```', re.DOTALL)
        matches = pattern.findall(ai_response)
        proposals = []

        for raw_path, code in matches:
            clean_path = raw_path.strip().replace("\\", "/")
            target_file = (self.project_path / clean_path).resolve()

            # Prevent path traversal
            try:
                target_file.relative_to(self.project_path)
            except ValueError:
                continue

            exists = target_file.exists()
            proposals.append(CodeModificationProposal(
                file_path=clean_path,
                action="modify" if exists else "create",
                code_content=code,
                original_exists=exists
            ))

        return proposals

    def apply_code_proposal(self, proposal: CodeModificationProposal) -> Dict[str, Any]:
        """Safely writes proposed code changes with an automatic backup."""
        if not self.project_path:
            raise ValueError("No project path active")

        target_file = (self.project_path / proposal.file_path).resolve()
        target_file.relative_to(self.project_path)  # Safety check

        backup_path = None
        if target_file.exists():
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_file = target_file.with_name(f"{target_file.name}.bak_{timestamp}")
            shutil.copy2(target_file, backup_file)
            backup_path = str(backup_file.relative_to(self.project_path))

        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(proposal.code_content)

        # Log to episodic memory
        if self.memory_mgr:
            self.memory_mgr.add_episodic_memory(EpisodicMemory(
                session_id="system",
                memory_type="code_change",
                summary=f"File {proposal.action}d: {proposal.file_path}",
                detail=f"Applied changes. Backup created: {backup_path or 'None'}",
                tags=f"code_change,{proposal.file_path}"
            ))

        return {
            "success": True,
            "file_path": proposal.file_path,
            "action": proposal.action,
            "backup_created": backup_path
        }

    def read_file_content(self, relative_path: str) -> Optional[str]:
        """Reads a project file content safely."""
        if not self.project_path:
            return None
        target = (self.project_path / relative_path).resolve()
        try:
            target.relative_to(self.project_path)
        except ValueError:
            return None

        if not target.exists() or not target.is_file():
            return None

        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return None
