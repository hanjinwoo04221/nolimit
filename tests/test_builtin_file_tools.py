import unittest
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

from src.core.project_manager import ProjectManager
from src.server.app import app

class TestBuiltinFileTools(unittest.TestCase):
    def setUp(self):
        # Create a temporary project directory for testing
        self.test_dir = tempfile.mkdtemp(prefix="contextforge_test_")
        self.project_path = Path(self.test_dir)
        
        # Create some sample files
        (self.project_path / "hello.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        sub_dir = self.project_path / "src"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "app.py").write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

        self.manager = ProjectManager()
        self.manager.set_project(str(self.project_path))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_builtin_tools_schema(self):
        schemas = self.manager.get_builtin_tools_schema()
        self.assertEqual(len(schemas), 4)
        tool_names = [s["function"]["name"] for s in schemas]
        self.assertIn("read_file", tool_names)
        self.assertIn("edit_file", tool_names)
        self.assertIn("create_file", tool_names)
        self.assertIn("list_dir", tool_names)

    def test_read_file_tool(self):
        # Full read
        res = self.manager.read_file_tool("hello.py")
        self.assertTrue(res["success"])
        self.assertIn("def hello():", res["content"])
        self.assertEqual(res["total_lines"], 2)

        # Slice read
        res_slice = self.manager.read_file_tool("src/app.py", start_line=2, end_line=4)
        self.assertTrue(res_slice["success"])
        self.assertEqual(res_slice["start_line"], 2)
        self.assertEqual(res_slice["end_line"], 4)
        self.assertEqual(res_slice["content"], "line2\nline3\nline4")

        # Non-existent file
        res_err = self.manager.read_file_tool("does_not_exist.py")
        self.assertIn("error", res_err)

        # Path traversal protection
        res_traversal = self.manager.read_file_tool("../../secret.txt")
        self.assertIn("error", res_traversal)
        self.assertIn("Access denied", res_traversal["error"])

    def test_edit_file_tool_and_backup(self):
        new_content = "def hello():\n    return 'contextforge'\n"
        res = self.manager.edit_file_tool("hello.py", new_content)
        self.assertTrue(res["success"])
        self.assertIn("backup_path", res)
        self.assertIn(".bak_", res["backup_path"])

        # Check file was updated
        read_back = (self.project_path / "hello.py").read_text(encoding="utf-8")
        self.assertEqual(read_back, new_content)

        # Check backup file exists with original content
        backup_path = self.project_path / res["backup_path"]
        self.assertTrue(backup_path.exists())
        self.assertIn("return 'world'", backup_path.read_text(encoding="utf-8"))

        # Test restore backup
        restore_res = self.manager.restore_backup(res["backup_path"], "hello.py")
        self.assertTrue(restore_res["success"])
        restored_content = (self.project_path / "hello.py").read_text(encoding="utf-8")
        self.assertIn("return 'world'", restored_content)

    def test_create_file_tool(self):
        res = self.manager.create_file_tool("nested/folder/new_file.txt", "Initial content")
        self.assertTrue(res["success"])
        created_file = self.project_path / "nested" / "folder" / "new_file.txt"
        self.assertTrue(created_file.exists())
        self.assertEqual(created_file.read_text(encoding="utf-8"), "Initial content")

    def test_list_dir_tool(self):
        res = self.manager.list_dir_tool(".")
        self.assertTrue(res["success"])
        item_names = [i["name"] for i in res["items"]]
        self.assertIn("hello.py", item_names)
        self.assertIn("src", item_names)

    def test_execute_builtin_tool_dispatcher(self):
        # Dict args
        res = self.manager.execute_builtin_tool("read_file", {"path": "hello.py"})
        self.assertTrue(res.get("success"))

        # String JSON args
        res_json_str = self.manager.execute_builtin_tool("read_file", '{"path": "hello.py"}')
        self.assertTrue(res_json_str.get("success"))

        # Raw string path args
        res_raw_str = self.manager.execute_builtin_tool("read_file", "hello.py")
        self.assertTrue(res_raw_str.get("success"))

        # None args
        res_none = self.manager.execute_builtin_tool("read_file", None)
        self.assertIn("error", res_none)

        res_unknown = self.manager.execute_builtin_tool("unknown_tool", {})
        self.assertIn("error", res_unknown)

        # Test history with strings in prepare_chat
        client = TestClient(app)
        client.post("/api/project/select", json={"project_path": str(self.project_path)})
        resp = client.post("/api/chat/prepare", json={
            "prompt": "test prompt",
            "history": [{"role": "user", "content": "hi"}],
            "custom_max_tokens": 4096
        })
        self.assertEqual(resp.status_code, 200)

    def test_file_api_endpoints(self):
        client = TestClient(app)
        
        # Select project via API
        select_resp = client.post("/api/project/select", json={"project_path": str(self.project_path)})
        self.assertEqual(select_resp.status_code, 200)

        # File tree
        tree_resp = client.get("/api/file/tree")
        self.assertEqual(tree_resp.status_code, 200)
        tree = tree_resp.json()["tree"]
        paths = [t["path"] for t in tree]
        self.assertTrue(any("hello.py" in p for p in paths))

        # Read file endpoint
        read_resp = client.post("/api/file/read", json={"file_path": "hello.py"})
        self.assertEqual(read_resp.status_code, 200)
        self.assertIn("def hello():", read_resp.json()["content"])

        # Edit file endpoint
        edit_resp = client.post("/api/file/edit", json={"file_path": "hello.py", "content": "# edited via API"})
        self.assertEqual(edit_resp.status_code, 200)
        self.assertTrue(edit_resp.json()["success"])

        # Verify edited
        verify_resp = client.post("/api/file/read", json={"file_path": "hello.py"})
        self.assertEqual(verify_resp.json()["content"], "# edited via API")

if __name__ == "__main__":
    unittest.main()
