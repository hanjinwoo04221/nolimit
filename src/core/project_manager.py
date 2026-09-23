import os
import json
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
from src.core.mcp_client import MCPManager, MCPServerConfig, MCPToolDefinition

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
        self.mcp_mgr = MCPManager()

        if self.project_path and self.project_path.exists():
            self._init_project(str(self.project_path))

    def _init_project(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        memory_dir = self.project_path / ".context_memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        db_path = memory_dir / "memory.db"
        self.memory_mgr = LongTermMemoryManager(str(db_path))
        self.assembler = DynamicContextAssembler(self.memory_mgr)
        
        # Load project-level MCP servers
        mcp_cfg_path = memory_dir / config.mcp_config_filename
        self.mcp_mgr = MCPManager(str(mcp_cfg_path))

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

    # --- Built-in File Operations & Tools ---

    def read_file_tool(self, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
        """Safely reads file contents with optional line range slice."""
        if not self.project_path:
            return {"error": "No project selected"}
        
        clean_path = path.strip().replace("\\", "/").lstrip("/")
        target = (self.project_path / clean_path).resolve()
        try:
            target.relative_to(self.project_path)
        except ValueError:
            return {"error": f"Access denied: Path '{path}' is outside the project root."}

        if not target.exists():
            return {"error": f"File not found: '{clean_path}'"}
        if not target.is_file():
            return {"error": f"Target is a directory, not a file: '{clean_path}'"}

        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)

        if start_line is not None or end_line is not None:
            s = max(1, start_line or 1)
            e = min(total_lines, end_line or total_lines)
            sliced_content = "".join(lines[s-1:e]).rstrip("\n")
            return {
                "success": True,
                "file_path": clean_path,
                "total_lines": total_lines,
                "lines_shown": f"{s}-{e}",
                "start_line": s,
                "end_line": e,
                "content": sliced_content
            }

        return {
            "success": True,
            "file_path": clean_path,
            "total_lines": total_lines,
            "content": content
        }

    def edit_file_tool(self, path: str, content: str) -> Dict[str, Any]:
        """Edits an existing file with automatic timestamped backup."""
        if not self.project_path:
            return {"error": "No project selected"}

        clean_path = path.strip().replace("\\", "/").lstrip("/")
        target = (self.project_path / clean_path).resolve()
        try:
            target.relative_to(self.project_path)
        except ValueError:
            return {"error": f"Access denied: Path '{path}' is outside project root."}

        backup_path = None
        if target.exists():
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_file = target.with_name(f"{target.name}.bak_{timestamp}")
            shutil.copy2(target, backup_file)
            backup_path = str(backup_file.relative_to(self.project_path)).replace("\\", "/")

        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        # Log change in episodic memory
        if self.memory_mgr:
            self.memory_mgr.add_episodic_memory(EpisodicMemory(
                session_id="system",
                memory_type="code_change",
                summary=f"File edited: {clean_path}",
                detail=f"Content updated ({len(content)} chars). Backup: {backup_path or 'None'}",
                tags=f"edit,{clean_path}"
            ))

        return {
            "success": True,
            "file_path": clean_path,
            "action": "edit",
            "backup_created": backup_path,
            "backup_path": backup_path,
            "bytes_written": len(content.encode('utf-8'))
        }

    def create_file_tool(self, path: str, content: str) -> Dict[str, Any]:
        """Creates a new file in the project."""
        if not self.project_path:
            return {"error": "No project selected"}

        clean_path = path.strip().replace("\\", "/").lstrip("/")
        target = (self.project_path / clean_path).resolve()
        try:
            target.relative_to(self.project_path)
        except ValueError:
            return {"error": f"Access denied: Path '{path}' is outside project root."}

        if target.exists():
            return {"error": f"File '{clean_path}' already exists. Use edit_file instead."}

        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        # Log to memory
        if self.memory_mgr:
            self.memory_mgr.add_episodic_memory(EpisodicMemory(
                session_id="system",
                memory_type="code_change",
                summary=f"File created: {clean_path}",
                detail=f"Created new file with {len(content)} chars.",
                tags=f"create,{clean_path}"
            ))

        return {
            "success": True,
            "file_path": clean_path,
            "action": "create",
            "bytes_written": len(content.encode('utf-8'))
        }

    def list_dir_tool(self, rel_path: str = ".") -> Dict[str, Any]:
        """Lists files and folders inside a project sub-directory."""
        if not self.project_path:
            return {"error": "No project selected"}

        clean_path = rel_path.strip().replace("\\", "/").lstrip("/")
        target = (self.project_path / clean_path).resolve()
        try:
            target.relative_to(self.project_path)
        except ValueError:
            return {"error": "Access denied: Path is outside project root."}

        if not target.exists() or not target.is_dir():
            return {"error": f"Directory not found: '{clean_path}'"}

        entries = []
        for item in sorted(target.iterdir()):
            if item.name.startswith(".") or item.name in config.ignored_directories:
                continue
            is_d = item.is_dir()
            entries.append({
                "name": item.name,
                "type": "directory" if is_d else "file",
                "relative_path": str(item.relative_to(self.project_path)).replace("\\", "/"),
                "size_bytes": item.stat().st_size if not is_d else 0
            })

        return {
            "success": True,
            "directory": clean_path or ".",
            "count": len(entries),
            "entries": entries,
            "items": entries
        }

    def restore_backup(self, backup_path: str, target_path: str) -> Dict[str, Any]:
        """Restores a file from its backup copy."""
        if not self.project_path:
            return {"error": "No project selected"}

        b_file = (self.project_path / backup_path).resolve()
        t_file = (self.project_path / target_path).resolve()
        b_file.relative_to(self.project_path)
        t_file.relative_to(self.project_path)

        if not b_file.exists():
            return {"error": f"Backup file not found: {backup_path}"}

        shutil.copy2(b_file, t_file)
        return {
            "success": True,
            "restored_to": target_path,
            "from_backup": backup_path
        }

    def get_project_file_tree(self) -> List[Dict[str, Any]]:
        """Returns flat file list for UI file explorer."""
        if not self.project_path or not self.project_path.exists():
            return []

        tree = []
        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in config.ignored_directories and not d.startswith(".")]
            for f in sorted(files):
                if f.startswith(".") or Path(f).suffix.lower() in config.ignored_extensions:
                    continue
                p = Path(root) / f
                try:
                    rel = str(p.relative_to(self.project_path)).replace("\\", "/")
                    tree.append({
                        "path": rel,
                        "name": f,
                        "size": p.stat().st_size
                    })
                except Exception:
                    continue
        return tree

    def get_builtin_tools_schema(self) -> List[Dict[str, Any]]:
        """Returns standard Function Calling schemas for built-in file operations."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the content of a file in the project. Use this whenever you need to inspect existing code or documentation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path (e.g. 'src/core/config.py')"},
                            "start_line": {"type": "integer", "description": "Optional 1-based start line"},
                            "end_line": {"type": "integer", "description": "Optional 1-based end line"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Edit or overwrite an existing file in the project. An automatic backup is created before writing.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path (e.g. 'src/utils.py')"},
                            "content": {"type": "string", "description": "The complete updated content to write into the file"}
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_file",
                    "description": "Create a new file in the project with the specified content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path for the new file"},
                            "content": {"type": "string", "description": "Initial content for the new file"}
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": "List files and subdirectories within a folder of the project.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rel_path": {"type": "string", "description": "Relative folder path (default: '.')"}
                        }
                    }
                }
            }
        ]

    def execute_builtin_tool(self, name: str, args: Any) -> Dict[str, Any]:
        """Executes a built-in file tool by name, safely handling dict, json string, or path string."""
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    args = parsed
                elif isinstance(parsed, str):
                    args = {"path": parsed}
                else:
                    args = {}
            except Exception:
                args = {"path": args.strip()} if args.strip() else {}
        elif not isinstance(args, dict):
            args = {}

        if name == "read_file":
            return self.read_file_tool(
                path=args.get("path", ""),
                start_line=args.get("start_line"),
                end_line=args.get("end_line")
            )
        elif name == "edit_file":
            return self.edit_file_tool(
                path=args.get("path", ""),
                content=args.get("content", "")
            )
        elif name == "create_file":
            return self.create_file_tool(
                path=args.get("path", ""),
                content=args.get("content", "")
            )
        elif name == "list_dir":
            return self.list_dir_tool(
                rel_path=args.get("rel_path", ".")
            )
        return {"error": f"Unknown built-in tool '{name}'"}

    # --- MCP Operations ---
    async def get_mcp_servers(self) -> Dict[str, Any]:
        """Returns all configured MCP servers and their current status."""
        return await self.mcp_mgr.connect_all()

    async def add_mcp_server(self, cfg: MCPServerConfig) -> Tuple[bool, str]:
        """Registers and connects an MCP server."""
        return await self.mcp_mgr.add_server(cfg)

    async def remove_mcp_server(self, name: str) -> bool:
        """Removes an MCP server."""
        return await self.mcp_mgr.remove_server(name)

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Returns list of all available MCP tools."""
        return [t.dict() for t in self.mcp_mgr.get_all_tools()]

    async def execute_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a tool on the responsible MCP server."""
        return await self.mcp_mgr.execute_tool(tool_name, arguments)
