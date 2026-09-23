import re
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

def estimate_tokens(text: str) -> int:
    """Rough token estimation suitable for both English, code symbols, and CJK characters."""
    if not text:
        return 0
    # CJK characters are typically 1 token each in LLM tokenizers, English words ~1.3 tokens
    cjk_count = len(re.findall(r'[\u3131-\uD79D\u4E00-\u9FFF\u3040-\u30FF]', text))
    other_chars = len(text) - cjk_count
    return max(1, int(cjk_count + (other_chars / 3.8)))

class CodeChunk(BaseModel):
    id: str
    file_path: str
    start_line: int
    end_line: int
    chunk_type: str = "block"  # 'function', 'class', 'header', 'block', 'text'
    symbol_name: Optional[str] = None
    content: str
    token_count: int

class SmartCodeChunker:
    def __init__(self, target_tokens: int = 350, overlap_tokens: int = 50):
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens

    def chunk_file(self, file_path: str, content: str) -> List[CodeChunk]:
        """Splits a file into semantic or line-based chunks with metadata."""
        if not content.strip():
            return []

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        ext = file_path.lower().split('.')[-1] if '.' in file_path else ''

        # If file is small enough to fit in a single chunk, return it directly
        total_tokens = estimate_tokens(content)
        if total_tokens <= self.target_tokens:
            chunk_id = hashlib.md5(f"{file_path}:1:{total_lines}".encode()).hexdigest()[:12]
            primary_symbol = file_path
            first_sym = re.search(r'(?:class|def|function|fn)\s+([a-zA-Z0-9_]+)', content)
            if first_sym:
                primary_symbol = first_sym.group(1)
            return [CodeChunk(
                id=chunk_id,
                file_path=file_path,
                start_line=1,
                end_line=total_lines,
                chunk_type="full_file",
                symbol_name=primary_symbol,
                content=content,
                token_count=total_tokens
            )]

        # Find symbol definition lines (functions, classes, headers)
        boundary_regex = re.compile(
            r'^(?:'
            r'(?:async\s+)?def\s+([a-zA-Z0-9_]+)|'                 # Python def
            r'class\s+([a-zA-Z0-9_]+)|'                            # Class (Py, JS, Java, etc.)
            r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)|' # JS/TS function
            r'(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|' # JS arrow func
            r'func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)|'            # Go func
            r'(?:pub\s+)?fn\s+([a-zA-Z0-9_]+)|'                    # Rust fn
            r'#{1,3}\s+(.+)'                                       # Markdown headers
            r')'
        )

        boundaries = []
        for i, line in enumerate(lines):
            match = boundary_regex.search(line.strip())
            if match:
                symbol = next((g for g in match.groups() if g), "unknown")
                chunk_type = "class" if "class" in line else ("header" if line.strip().startswith("#") else "function")
                boundaries.append((i, symbol, chunk_type))

        chunks: List[CodeChunk] = []
        
        # If boundaries found, use them as split anchors
        if boundaries:
            prev_line_idx = 0
            prev_symbol = "file_start"
            prev_type = "header"

            for b_idx, symbol, c_type in boundaries:
                if b_idx > prev_line_idx:
                    block_content = "".join(lines[prev_line_idx:b_idx])
                    block_tokens = estimate_tokens(block_content)
                    if block_tokens > 0:
                        if block_tokens > self.target_tokens * 1.5:
                            # Subdivide oversized block
                            sub_chunks = self._subdivide_lines(file_path, lines[prev_line_idx:b_idx], prev_line_idx + 1, prev_symbol, prev_type)
                            chunks.extend(sub_chunks)
                        else:
                            c_id = hashlib.md5(f"{file_path}:{prev_line_idx+1}:{b_idx}".encode()).hexdigest()[:12]
                            chunks.append(CodeChunk(
                                id=c_id,
                                file_path=file_path,
                                start_line=prev_line_idx + 1,
                                end_line=b_idx,
                                chunk_type=prev_type,
                                symbol_name=prev_symbol,
                                content=block_content,
                                token_count=block_tokens
                            ))
                prev_line_idx = b_idx
                prev_symbol = symbol
                prev_type = c_type

            # Remainder of file
            if prev_line_idx < total_lines:
                block_content = "".join(lines[prev_line_idx:total_lines])
                block_tokens = estimate_tokens(block_content)
                if block_tokens > self.target_tokens * 1.5:
                    sub_chunks = self._subdivide_lines(file_path, lines[prev_line_idx:total_lines], prev_line_idx + 1, prev_symbol, prev_type)
                    chunks.extend(sub_chunks)
                else:
                    c_id = hashlib.md5(f"{file_path}:{prev_line_idx+1}:{total_lines}".encode()).hexdigest()[:12]
                    chunks.append(CodeChunk(
                        id=c_id,
                        file_path=file_path,
                        start_line=prev_line_idx + 1,
                        end_line=total_lines,
                        chunk_type=prev_type,
                        symbol_name=prev_symbol,
                        content=block_content,
                        token_count=block_tokens
                    ))
        else:
            # Fallback to rolling line window
            chunks = self._subdivide_lines(file_path, lines, 1, file_path, "block")

        return chunks

    def _subdivide_lines(self, file_path: str, lines: List[str], start_offset: int, symbol: str, chunk_type: str) -> List[CodeChunk]:
        """Splits a list of lines into overlapping windows conforming to target_tokens."""
        chunks = []
        current_chunk_lines = []
        current_tokens = 0
        chunk_start_line = start_offset

        for idx, line in enumerate(lines):
            line_tokens = estimate_tokens(line)
            if current_tokens + line_tokens > self.target_tokens and current_chunk_lines:
                end_line = chunk_start_line + len(current_chunk_lines) - 1
                c_content = "".join(current_chunk_lines)
                c_id = hashlib.md5(f"{file_path}:{chunk_start_line}:{end_line}".encode()).hexdigest()[:12]
                chunks.append(CodeChunk(
                    id=c_id,
                    file_path=file_path,
                    start_line=chunk_start_line,
                    end_line=end_line,
                    chunk_type=chunk_type,
                    symbol_name=symbol,
                    content=c_content,
                    token_count=current_tokens
                ))
                
                # Overlap: keep last few lines that sum to ~overlap_tokens
                overlap_lines = []
                overlap_tokens_count = 0
                for rev_line in reversed(current_chunk_lines):
                    r_tok = estimate_tokens(rev_line)
                    if overlap_tokens_count + r_tok <= self.overlap_tokens:
                        overlap_lines.insert(0, rev_line)
                        overlap_tokens_count += r_tok
                    else:
                        break
                
                current_chunk_lines = overlap_lines
                current_tokens = overlap_tokens_count
                chunk_start_line = start_offset + idx - len(overlap_lines)

            current_chunk_lines.append(line)
            current_tokens += line_tokens

        if current_chunk_lines:
            end_line = chunk_start_line + len(current_chunk_lines) - 1
            c_content = "".join(current_chunk_lines)
            c_id = hashlib.md5(f"{file_path}:{chunk_start_line}:{end_line}".encode()).hexdigest()[:12]
            chunks.append(CodeChunk(
                id=c_id,
                file_path=file_path,
                start_line=chunk_start_line,
                end_line=end_line,
                chunk_type=chunk_type,
                symbol_name=symbol,
                content=c_content,
                token_count=current_tokens
            ))

        return chunks
