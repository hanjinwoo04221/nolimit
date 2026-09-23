import unittest
from fastapi.testclient import TestClient
from src.server.app import app

class TestAPIIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("llm_health", data)

    def test_models_list(self):
        resp = self.client.get("/api/models?provider=ollama")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["provider"], "ollama")
        self.assertIsInstance(data["models"], list)

    def test_project_select_and_prepare(self):
        # Select current project
        resp = self.client.post("/api/project/select", json={"project_path": "."})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_indexed"])
        self.assertGreater(data["stats"]["total_files"], 0)

        # Prepare chat context
        chat_resp = self.client.post("/api/chat/prepare", json={
            "prompt": "청커(chunker)가 어떻게 동작하는지 설명해줘",
            "history": [],
            "custom_max_tokens": 4096
        })
        self.assertEqual(chat_resp.status_code, 200)
        context_data = chat_resp.json()
        self.assertIn("system_prompt", context_data)
        self.assertIn("budget_breakdown", context_data)
        self.assertGreater(len(context_data["retrieved_chunks"]), 0)
        
        # Verify chunker was matched
        matched_files = [c["file_path"] for c in context_data["retrieved_chunks"]]
        self.assertTrue(any("chunker" in f for f in matched_files))

if __name__ == "__main__":
    unittest.main()
