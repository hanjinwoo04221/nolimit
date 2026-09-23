import unittest
from src.core.chunker import SmartCodeChunker, estimate_tokens

class TestChunker(unittest.TestCase):
    def setUp(self):
        self.chunker = SmartCodeChunker(target_tokens=100, overlap_tokens=20)

    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertGreater(estimate_tokens("hello world"), 1)
        self.assertGreater(estimate_tokens("안녕하세요 반갑습니다"), 5)

    def test_chunk_file_boundary_detection(self):
        sample_code = """
import os

class DatabaseClient:
    def __init__(self, host: str):
        self.host = host

    def connect(self):
        return f"Connected to {self.host}"

class CacheManager:
    def get(self, key: str):
        return "cached_val"
"""
        chunks = self.chunker.chunk_file("db.py", sample_code)
        self.assertGreater(len(chunks), 0)
        self.assertTrue(any(c.symbol_name in ["DatabaseClient", "CacheManager", "connect", "get"] for c in chunks))
        for c in chunks:
            self.assertEqual(c.file_path, "db.py")
            self.assertGreater(c.end_line, 0)
            self.assertGreater(c.token_count, 0)

if __name__ == "__main__":
    unittest.main()
