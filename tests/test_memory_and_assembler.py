import unittest
import tempfile
import os
from src.core.chunker import CodeChunk
from src.core.memory import LongTermMemoryManager, EpisodicMemory
from src.core.context_assembler import DynamicContextAssembler, DialogueTurn

class TestMemoryAndAssembler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_memory.db")
        self.memory = LongTermMemoryManager(self.db_path)

        # Seed sample chunks
        self.sample_chunks = [
            CodeChunk(
                id=f"chunk_{i}",
                file_path=f"src/service_{i}.py",
                start_line=1,
                end_line=50,
                chunk_type="function",
                symbol_name=f"handler_{i}",
                content=f"def handler_{i}():\n    # Service {i} logic\n    pass\n" * 10,
                token_count=120
            )
            for i in range(15)  # Total 15 * 120 = 1800 tokens of project code
        ]
        self.memory.save_project_chunks(self.sample_chunks, repo_map="# Test Project Map")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_episodic_memory_storage_and_recall(self):
        mem = EpisodicMemory(
            session_id="test_sess",
            memory_type="decision",
            summary="Decided to use PostgreSQL for user auth",
            detail="PostgreSQL chosen over MongoDB for relational integrity",
            tags="db,decision"
        )
        self.memory.add_episodic_memory(mem)

        # Retrieve
        recalled = self.memory.retrieve_relevant_memories("PostgreSQL user auth", session_id="test_sess", top_k=2)
        self.assertGreater(len(recalled), 0)
        self.assertIn("PostgreSQL", recalled[0][0].summary)

    def test_context_assembler_budget_limit(self):
        assembler = DynamicContextAssembler(self.memory)

        # Set a tight budget of 1500 tokens
        max_budget = 1500
        dialogue = [
            DialogueTurn(role="user", content="첫 번째 대화입니다."),
            DialogueTurn(role="assistant", content="네, 프로젝트를 파악했습니다."),
        ]

        assembled = assembler.assemble(
            current_prompt="service_3 handler_3 어떻게 동작해?",
            dialogue_history=dialogue,
            session_id="test_sess",
            custom_max_tokens=max_budget
        )

        # Verify the assembled total tokens do NOT exceed the max budget
        self.assertLessEqual(assembled.total_estimated_tokens, max_budget)
        # Verify that relevant chunk for service_3 was retrieved
        retrieved_files = [c["file_path"] for c in assembled.retrieved_chunks]
        self.assertTrue(any("service_3" in f for f in retrieved_files))
        # Verify budget breakdown was populated
        self.assertIn("total_input", assembled.budget_breakdown)
        self.assertGreater(assembled.compression_ratio, 0.0)

if __name__ == "__main__":
    unittest.main()
