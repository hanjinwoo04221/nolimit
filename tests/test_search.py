import unittest
from src.core.chunker import CodeChunk
from src.core.search import HybridSearchEngine, BM25Engine, tokenize

class TestSearch(unittest.TestCase):
    def setUp(self):
        self.engine = HybridSearchEngine()
        self.chunks = [
            CodeChunk(
                id="c1",
                file_path="src/auth.py",
                start_line=1,
                end_line=25,
                chunk_type="function",
                symbol_name="login_user",
                content="def login_user(username, password):\n    # Authenticate credentials and return JWT token\n    return generate_jwt(username)",
                token_count=30
            ),
            CodeChunk(
                id="c2",
                file_path="src/database.py",
                start_line=1,
                end_line=40,
                chunk_type="function",
                symbol_name="connect_db",
                content="def connect_db():\n    # Connect to PostgreSQL cluster\n    return psycopg2.connect()",
                token_count=25
            ),
            CodeChunk(
                id="c3",
                file_path="src/payment.py",
                start_line=1,
                end_line=30,
                chunk_type="function",
                symbol_name="process_payment",
                content="def process_payment(amount, card_token):\n    # Stripe credit card checkout flow\n    return stripe.Charge.create()",
                token_count=35
            )
        ]
        self.engine.build_index(self.chunks)

    def test_bm25_symbol_match(self):
        results = self.engine.search("login_user", top_k=2)
        self.assertGreater(len(results), 0)
        top_chunk, score, reason = results[0]
        self.assertEqual(top_chunk.id, "c1")
        self.assertEqual(top_chunk.file_path, "src/auth.py")

    def test_semantic_match(self):
        # Query uses natural language concepts: "결제 카드 승인" / "credit card checkout"
        results = self.engine.search("credit card checkout payment", top_k=2)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0][0].id, "c3")

    def test_path_boosting(self):
        results = self.engine.search("database.py", top_k=2)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0][0].id, "c2")

if __name__ == "__main__":
    unittest.main()
