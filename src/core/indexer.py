import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from pydantic import BaseModel
from src.core.config import config
from src.core.chunker import SmartCodeChunker, CodeChunk, estimate_tokens

class FileMetadata(BaseModel):
    relative_path: str
    absolute_path: str
    extension: str
    size_bytes: int
    line_count: int
    token_count: int
    summary: str = ""

class ProjectIndexSummary(BaseModel):
    project_root: str
    total_files: int
    total_chunks: int
    total_tokens: int
    total_lines: int
    repo_map: str
    files: List[FileMetadata]

class ProjectIndexer:
    def __init__(self, target_tokens: int = 350, overlap_tokens: int = 50):
        self.chunker = SmartCodeChunker(target_tokens=target_tokens, overlap_tokens=overlap_tokens)

    def scan_project(self, project_path: str) -> Tuple[List[FileMetadata], List[CodeChunk], str]:
        """
        Scans a project directory, produces file metadata, chunks, and a high-signal repo map.
        """
        root = Path(project_path).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Project directory does not exist or is not a directory: {project_path}")

        files_meta: List[FileMetadata] = []
        all_chunks: List[CodeChunk] = []
        file_tree_lines: List[str] = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune ignored directories in-place
            dirnames[:] = [
                d for d in dirnames 
                if d not in config.ignored_directories 
                and not d.startswith(".")
            ]

            rel_dir = os.path.relpath(dirpath, root)
            if rel_dir == ".":
                depth = 0
            else:
                depth = len(Path(rel_dir).parts)

            indent = "  " * depth
            dir_name = os.path.basename(dirpath) if rel_dir != "." else root.name
            if rel_dir != ".":
                file_tree_lines.append(f"{indent}📂 {dir_name}/")

            for fname in sorted(filenames):
                ext = Path(fname).suffix.lower()
                if ext in config.ignored_extensions or fname.startswith("."):
                    continue

                abs_file = Path(dirpath) / fname
                rel_file = str(abs_file.relative_to(root)).replace("\\", "/")

                # Size check
                try:
                    size = abs_file.stat().st_size
                except OSError:
                    continue

                if size > config.max_file_size_bytes or size == 0:
                    continue

                # Read text content
                try:
                    with open(abs_file, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue

                # Quick binary check: null bytes
                if "\x00" in content:
                    continue

                lines = content.splitlines()
                line_count = len(lines)
                tokens = estimate_tokens(content)

                # Generate brief one-line summary (top docstring or first non-empty lines)
                summary = self._extract_summary(content, fname)

                meta = FileMetadata(
                    relative_path=rel_file,
                    absolute_path=str(abs_file),
                    extension=ext,
                    size_bytes=size,
                    line_count=line_count,
                    token_count=tokens,
                    summary=summary
                )
                files_meta.append(meta)

                # Add to repo tree
                tree_indent = "  " * (depth + (1 if rel_dir != "." else 0))
                summary_hint = f"  # {summary}" if summary else ""
                file_tree_lines.append(f"{tree_indent}📄 {fname} ({line_count} lines, ~{tokens} tok){summary_hint}")

                # Chunk the file
                chunks = self.chunker.chunk_file(rel_file, content)
                all_chunks.extend(chunks)

        repo_map = self._build_repo_map(root.name, file_tree_lines, len(files_meta), sum(m.token_count for m in files_meta))
        return files_meta, all_chunks, repo_map

    def _extract_summary(self, content: str, filename: str) -> str:
        """Extracts brief file purpose or main export."""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return ""
        
        # Check first 5 lines for comments or docstrings
        for line in lines[:5]:
            if line.startswith(("#", "//", "/*", "*", '"""', "'''")):
                clean = line.lstrip("#/* \t'\"").strip()
                if clean and len(clean) > 5:
                    return clean[:60]
        return ""

    def _build_repo_map(self, root_name: str, tree_lines: List[str], total_files: int, total_tokens: int) -> str:
        """Constructs a clean, compact markdown representation of the repository."""
        header = f"# Project Architecture Map: {root_name} ({total_files} files, ~{total_tokens:,} tokens)\n"
        if len(tree_lines) > 120:
            # If repo is huge, show first 100 items + truncated note
            body = "\n".join(tree_lines[:100]) + f"\n  ... and {len(tree_lines) - 100} more files."
        else:
            body = "\n".join(tree_lines)
        return header + "```text\n" + body + "\n```"
