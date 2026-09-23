from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional

class SystemConfig(BaseModel):
    # LLM Settings
    provider: str = Field(default="ollama", description="LLM provider: 'ollama' or 'openai_compatible'")
    ollama_url: str = Field(default="http://localhost:11434", description="Ollama API base URL")
    openai_url: str = Field(default="http://localhost:1234/v1", description="OpenAI-compatible base URL")
    openai_api_key: str = Field(default="not-needed", description="API Key for OpenAI-compatible server")
    model_name: str = Field(default="qwen2.5-coder:7b", description="Model name to use")
    embedding_model: str = Field(default="nomic-embed-text", description="Ollama embedding model (optional)")
    
    # Context Budgeting (in tokens, ~4 chars per token rule of thumb)
    max_context_tokens: int = Field(default=4096, description="Total context window limit for the local model")
    max_output_tokens: int = Field(default=800, description="Tokens reserved for model completion response")
    
    # Budget distribution (percentages)
    system_ratio: float = 0.12     # System instructions & base persona
    repo_map_ratio: float = 0.10   # High-level directory / architecture map
    code_chunks_ratio: float = 0.48 # Retrieved relevant code snippets from project memory
    memories_ratio: float = 0.10   # Retrieved episodic memories & decisions
    dialogue_ratio: float = 0.20   # Recent dialogue turns (working memory)
    
    # Chunker settings
    chunk_size_tokens: int = Field(default=350, description="Target chunk size in tokens")
    chunk_overlap_tokens: int = Field(default=50, description="Overlap between consecutive chunks")
    
    # Retrieval settings
    top_k_chunks: int = Field(default=8, description="Max code chunks to retrieve")
    top_k_memories: int = Field(default=4, description="Max episodic memories to retrieve")
    
    # File scanner settings
    ignored_directories: List[str] = [
        ".git", ".svn", ".hg", "node_modules", "vendor", "venv", ".venv", "env",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "dist", "build", "target", "out", "bin", "obj", ".idea", ".vscode",
        ".context_memory", "coverage", ".next", ".nuxt", ".turbo"
    ]
    ignored_extensions: List[str] = [
        ".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".zip", ".tar", ".gz",
        ".7z", ".rar", ".pdf", ".docx", ".xlsx", ".pptx", ".png", ".jpg", ".jpeg",
        ".gif", ".webp", ".ico", ".svg", ".mp4", ".mov", ".avi", ".mp3", ".wav",
        ".pyc", ".pyd", ".class", ".jar", ".war", ".lock", ".wasm"
    ]
    max_file_size_bytes: int = 500 * 1024  # 500 KB per file limit for indexing

config = SystemConfig()
