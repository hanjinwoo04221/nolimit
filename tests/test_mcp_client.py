import unittest
import asyncio
import tempfile
import sys
import os
from pathlib import Path
from src.core.mcp_client import MCPServerConfig, MCPClient, MCPManager

MOCK_SERVER_SCRIPT = """
import sys
import json

for line in sys.stdin:
    if not line.strip():
        continue
    try:
        req = json.loads(line)
        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "MockServer", "version": "1.0.0"}
                }
            }
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()

        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "calc_sum",
                            "description": "Calculate sum of numbers",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"}
                                },
                                "required": ["x", "y"]
                            }
                        }
                    ]
                }
            }
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()

        elif method == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            total = args.get("x", 0) + args.get("y", 0)
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Sum is {total}"}],
                    "isError": False
                }
            }
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()

    except Exception:
        pass
"""

class TestMCPClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.server_py = Path(self.temp_dir.name) / "mock_mcp_server.py"
        with open(self.server_py, "w", encoding="utf-8") as f:
            f.write(MOCK_SERVER_SCRIPT)

        self.cfg_file = Path(self.temp_dir.name) / "mcp_servers.json"
        self.manager = MCPManager(str(self.cfg_file))

    async def asyncTearDown(self):
        await self.manager.close()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    async def test_mcp_stdio_connect_and_call(self):
        # Configure stdio MCP server pointing to mock python script
        server_cfg = MCPServerConfig(
            name="mock_calculator",
            transport="stdio",
            command=sys.executable,
            args=[str(self.server_py)],
            enabled=True
        )

        ok, msg = await self.manager.add_server(server_cfg)
        self.assertTrue(ok, f"Failed to connect: {msg}")

        # Check discovered tools
        tools = self.manager.get_all_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "calc_sum")
        self.assertEqual(tools[0].server_name, "mock_calculator")

        # Check format for LLM
        llm_tools = self.manager.get_tools_for_llm()
        self.assertEqual(len(llm_tools), 1)
        self.assertEqual(llm_tools[0]["function"]["name"], "mock_calculator__calc_sum")

        # Execute tool
        call_res = await self.manager.execute_tool("mock_calculator__calc_sum", {"x": 10, "y": 25})
        self.assertTrue(call_res.get("success"))
        content = call_res.get("result", {}).get("content", [])
        self.assertEqual(content[0]["text"], "Sum is 35")

    async def test_mcp_config_persistence(self):
        server_cfg = MCPServerConfig(
            name="test_persist",
            transport="stdio",
            command="uvx",
            args=["mcp-server-fetch"],
            enabled=False
        )
        await self.manager.add_server(server_cfg)
        self.assertTrue(self.cfg_file.exists())

        # Load fresh manager
        new_mgr = MCPManager(str(self.cfg_file))
        self.assertIn("test_persist", new_mgr.server_configs)
        self.assertEqual(new_mgr.server_configs["test_persist"].command, "uvx")

if __name__ == "__main__":
    unittest.main()
