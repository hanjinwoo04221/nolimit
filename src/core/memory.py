import sqlite3
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
from src.core.chunker import CodeChunk, estimate_tokens
from src.core.search import HybridSearchEngine

class EpisodicMemory(BaseModel):
    id: Optional[int] = None
    session_id: str = "default"
    memory_type: str  # 'turn', 'decision', 'code_change', 'user_rule'
    summary: str
    detail: str
    tags: str = ""
    timestamp: float = 0.0

class LongTermMemoryManager:
    """
    Persistent Long-Term Memory (LTM) engine backed by SQLite.
    Manages:
    1. Project Code Chunks & Search Index
    2. Episodic Conversation Turns & Milestone Decisions
    3. Working Memory (Recent Turns)
    """
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.search_engine = HybridSearchEngine()
        self.memory_search_engine = HybridSearchEngine()
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Project code chunks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS project_chunks (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    chunk_type TEXT,
                    symbol_name TEXT,
                    content TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON project_chunks(file_path)")

            # 2. Episodic memory table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    tags TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_session ON episodic_memories(session_id)")

            # 3. Project metadata cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS project_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.commit()

    # --- Project Codebase Memory Operations ---

    def save_project_chunks(self, chunks: List[CodeChunk], repo_map: str):
        """Persists project chunks and updates search index."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_chunks")
            for c in chunks:
                cursor.execute("""
                    INSERT INTO project_chunks (
                        id, file_path, start_line, end_line, chunk_type, symbol_name, content, token_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (c.id, c.file_path, c.start_line, c.end_line, c.chunk_type, c.symbol_name, c.content, c.token_count, now))
            
            # Save repo map
            cursor.execute("INSERT OR REPLACE INTO project_metadata (key, value) VALUES ('repo_map', ?)", (repo_map,))
            conn.commit()

        # Update in-memory search index
        self.search_engine.build_index(chunks)

    def load_project_chunks(self) -> Tuple[List[CodeChunk], str]:
        """Loads chunks from SQLite and builds the search index."""
        chunks: List[CodeChunk] = []
        repo_map = ""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, file_path, start_line, end_line, chunk_type, symbol_name, content, token_count FROM project_chunks")
            rows = cursor.fetchall()
            for r in rows:
                chunks.append(CodeChunk(
                    id=r[0],
                    file_path=r[1],
                    start_line=r[2],
                    end_line=r[3],
                    chunk_type=r[4],
                    symbol_name=r[5],
                    content=r[6],
                    token_count=r[7]
                ))

            cursor.execute("SELECT value FROM project_metadata WHERE key = 'repo_map'")
            m_row = cursor.fetchone()
            if m_row:
                repo_map = m_row[0]

        if chunks:
            self.search_engine.build_index(chunks)
        return chunks, repo_map

    def retrieve_relevant_code(self, query: str, top_k: int = 8) -> List[Tuple[CodeChunk, float, str]]:
        """Retrieves top-k code chunks from project memory matching the query."""
        return self.search_engine.search(query, top_k=top_k)

    # --- Episodic Memory Operations ---

    def add_episodic_memory(self, memory: EpisodicMemory):
        """Stores a new milestone, decision, or conversation turn into long-term memory."""
        now = memory.timestamp or time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO episodic_memories (session_id, memory_type, summary, detail, tags, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (memory.session_id, memory.memory_type, memory.summary, memory.detail, memory.tags, now))
            conn.commit()
            memory.id = cursor.lastrowid

    def get_recent_memories(self, session_id: str, limit: int = 20) -> List[EpisodicMemory]:
        """Fetches the most recent episodic memories for the session."""
        results: List[EpisodicMemory] = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, session_id, memory_type, summary, detail, tags, timestamp
                FROM episodic_memories
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, limit))
            for row in cursor.fetchall():
                results.append(EpisodicMemory(
                    id=row[0],
                    session_id=row[1],
                    memory_type=row[2],
                    summary=row[3],
                    detail=row[4],
                    tags=row[5] or "",
                    timestamp=row[6]
                ))
        return list(reversed(results))

    def retrieve_relevant_memories(self, query: str, session_id: str, top_k: int = 4) -> List[Tuple[EpisodicMemory, float]]:
        """
        Searches episodic memory to recall relevant past actions, decisions, or dialogue.
        """
        all_mems = self.get_recent_memories(session_id=session_id, limit=100)
        if not all_mems:
            return []

        # Convert memories to pseudo-chunks for the search engine
        pseudo_chunks: List[CodeChunk] = []
        for mem in all_mems:
            c_text = f"[{mem.memory_type.upper()}] {mem.summary}\n{mem.detail}\nTags: {mem.tags}"
            pseudo_chunks.append(CodeChunk(
                id=str(mem.id),
                file_path=f"memory://{mem.session_id}/{mem.memory_type}",
                start_line=1,
                end_line=1,
                chunk_type="memory",
                symbol_name=mem.memory_type,
                content=c_text,
                token_count=estimate_tokens(c_text)
            ))

        self.memory_search_engine.build_index(pseudo_chunks)
        results = self.memory_search_engine.search(query, top_k=top_k)

        mem_map = {m.id: m for m in all_mems}
        matched: List[Tuple[EpisodicMemory, float]] = []
        for chunk, score, _ in results:
            try:
                mem_id = int(chunk.id)
                if mem_id in mem_map:
                    matched.append((mem_map[mem_id], score))
            except ValueError:
                pass
        return matched

    def clear_session(self, session_id: str):
        """Clears memory for a specific session."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM episodic_memories WHERE session_id = ?", (session_id,))
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        """Returns statistics on stored memory."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(token_count) FROM project_chunks")
            c_row = cursor.fetchone()
            total_chunks = c_row[0] or 0
            total_tokens = c_row[1] or 0

            cursor.execute("SELECT COUNT(DISTINCT file_path) FROM project_chunks")
            total_files = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM episodic_memories")
            total_memories = cursor.fetchone()[0] or 0

        return {
            "total_files": total_files,
            "total_chunks": total_chunks,
            "total_tokens": total_tokens,
            "total_memories": total_memories
        }
