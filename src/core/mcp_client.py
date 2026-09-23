import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import httpx
from pydantic import BaseModel, Field

class MCPServerConfig(BaseModel):
    name: str
    transport: str = Field(default="stdio", description="'stdio' or 'sse'")
    command: Optional[str] = None  # e.g. 'uvx', 'npx', 'python'
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None  # for SSE transport
    enabled: bool = True

class MCPToolDefinition(BaseModel):
    server_name: str
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)

class MCPClient:
    """
    Standard Model Context Protocol (MCP) Client supporting stdio and SSE transports.
    Complies with JSON-RPC 2.0 specifications.
    """
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.is_connected = False
        self.tools: List[MCPToolDefinition] = []
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None

    async def connect(self, timeout: float = 10.0) -> bool:
        """Connects to the MCP server and completes the initialize handshake."""
        try:
            if self.config.transport == "stdio":
                await self._connect_stdio()
            elif self.config.transport == "sse":
                await self._connect_sse()
            else:
                raise ValueError(f"Unsupported transport: {self.config.transport}")

            # 1. Initialize Handshake
            init_res = await asyncio.wait_for(self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "clientInfo": {
                    "name": "ContextForge",
                    "version": "1.0.0"
                }
            }), timeout=timeout)

            # 2. Initialized Notification
            await self._send_notification("notifications/initialized", {})

            # 3. Discover Tools
            await self.refresh_tools()

            self.is_connected = True
            return True

        except Exception as e:
            self.is_connected = False
            await self.disconnect()
            raise RuntimeError(f"Failed to connect to MCP server '{self.config.name}': {e}")

    async def _connect_stdio(self):
        if not self.config.command:
            raise ValueError("Command is required for stdio transport")

        cmd = self.config.command
        # On Windows, resolve .cmd or .exe if needed (e.g. npx -> npx.cmd)
        if sys.platform == "win32":
            resolved = shutil.which(cmd)
            if resolved:
                cmd = resolved

        # Merge environment variables
        env = os.environ.copy()
        env.update(self.config.env)

        self._process = await asyncio.create_subprocess_exec(
            cmd,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        self._reader_task = asyncio.create_task(self._stdio_reader_loop())

    async def _stdio_reader_loop(self):
        """Reads newline-delimited JSON-RPC responses from stdout."""
        try:
            while self._process and self._process.stdout:
                line = await self._process.stdout.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                try:
                    data = json.loads(text)
                    req_id = data.get("id")
                    if req_id is not None and req_id in self._pending_requests:
                        future = self._pending_requests.pop(req_id)
                        if not future.done():
                            if "error" in data:
                                future.set_exception(RuntimeError(data["error"].get("message", "MCP error")))
                            else:
                                future.set_result(data.get("result", {}))
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _connect_sse(self):
        if not self.config.url:
            raise ValueError("URL is required for SSE transport")
        # For simple HTTP-based MCP or SSE, test reachability
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(self.config.url)
            if resp.status_code not in [200, 404]:
                raise RuntimeError(f"HTTP status {resp.status_code} from {self.config.url}")

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Any:
        self._request_id += 1
        req_id = self._request_id

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }

        if self.config.transport == "stdio":
            if not self._process or not self._process.stdin:
                raise RuntimeError("Process stdin is not open")

            future = asyncio.get_running_loop().create_future()
            self._pending_requests[req_id] = future

            msg = json.dumps(payload) + "\n"
            self._process.stdin.write(msg.encode("utf-8"))
            await self._process.stdin.drain()

            return await future
        else:
            # SSE / HTTP POST fallback for remote MCP servers
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(self.config.url, json=payload)
                data = res.json()
                if "error" in data:
                    raise RuntimeError(data["error"].get("message", "MCP error"))
                return data.get("result", {})

    async def _send_notification(self, method: str, params: Dict[str, Any]):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        if self.config.transport == "stdio" and self._process and self._process.stdin:
            msg = json.dumps(payload) + "\n"
            self._process.stdin.write(msg.encode("utf-8"))
            await self._process.stdin.drain()

    async def refresh_tools(self) -> List[MCPToolDefinition]:
        """Queries the MCP server for available tools (tools/list)."""
        res = await self._send_request("tools/list", {})
        raw_tools = res.get("tools", [])
        self.tools = []
        for t in raw_tools:
            self.tools.append(MCPToolDefinition(
                server_name=self.config.name,
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {})
            ))
        return self.tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Calls a tool on the MCP server and returns the result."""
        res = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        return res

    async def disconnect(self):
        """Terminates process and cleans up resources."""
        self.is_connected = False
        if self._reader_task:
            self._reader_task.cancel()
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except Exception:
                if self._process:
                    self._process.kill()
            self._process = None

class MCPManager:
    """
    Manages multiple MCP server connections, configurations, and tool executions.
    Persists configuration in standard mcp_servers.json format.
    """
    def __init__(self, config_file_path: Optional[str] = None):
        self.config_path = Path(config_file_path) if config_file_path else Path(".context_memory/mcp_servers.json")
        self.clients: Dict[str, MCPClient] = {}
        self.server_configs: Dict[str, MCPServerConfig] = {}
        self.load_config()

    def load_config(self):
        """Loads mcp_servers.json if it exists."""
        self.server_configs = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                raw_servers = data.get("mcpServers", {})
                for name, s_data in raw_servers.items():
                    transport = s_data.get("transport", "stdio" if "command" in s_data else "sse")
                    self.server_configs[name] = MCPServerConfig(
                        name=name,
                        transport=transport,
                        command=s_data.get("command"),
                        args=s_data.get("args", []),
                        env=s_data.get("env", {}),
                        url=s_data.get("url"),
                        enabled=s_data.get("enabled", True)
                    )
            except Exception as e:
                print(f"Warning: Could not parse {self.config_path}: {e}")

    def save_config(self):
        """Saves current server configs to mcp_servers.json."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        export_data = {"mcpServers": {}}
        for name, cfg in self.server_configs.items():
            s_dict = {
                "transport": cfg.transport,
                "enabled": cfg.enabled
            }
            if cfg.transport == "stdio":
                s_dict["command"] = cfg.command
                s_dict["args"] = cfg.args
                if cfg.env:
                    s_dict["env"] = cfg.env
            else:
                s_dict["url"] = cfg.url
            export_data["mcpServers"][name] = s_dict

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

    async def add_server(self, config: MCPServerConfig) -> Tuple[bool, str]:
        """Adds and attempts connection to an MCP server."""
        self.server_configs[config.name] = config
        self.save_config()

        if config.enabled:
            client = MCPClient(config)
            try:
                await client.connect(timeout=8.0)
                self.clients[config.name] = client
                return True, f"Connected to '{config.name}' with {len(client.tools)} tools."
            except Exception as e:
                return False, str(e)
        return True, f"Server '{config.name}' saved (disabled)."

    async def remove_server(self, name: str) -> bool:
        """Removes and disconnects an MCP server."""
        if name in self.clients:
            await self.clients[name].disconnect()
            del self.clients[name]
        if name in self.server_configs:
            del self.server_configs[name]
            self.save_config()
            return True
        return False

    async def connect_all(self) -> Dict[str, Dict[str, Any]]:
        """Connects to all enabled MCP servers."""
        results = {}
        for name, cfg in self.server_configs.items():
            if not cfg.enabled:
                results[name] = {"connected": False, "status": "Disabled", "tools": []}
                continue

            if name in self.clients and self.clients[name].is_connected:
                results[name] = {
                    "connected": True,
                    "status": "Online",
                    "tools": [t.dict() for t in self.clients[name].tools]
                }
                continue

            client = MCPClient(cfg)
            try:
                await client.connect(timeout=6.0)
                self.clients[name] = client
                results[name] = {
                    "connected": True,
                    "status": "Online",
                    "tools": [t.dict() for t in client.tools]
                }
            except Exception as e:
                results[name] = {
                    "connected": False,
                    "status": f"Error: {e}",
                    "tools": []
                }
        return results

    def get_all_tools(self) -> List[MCPToolDefinition]:
        """Returns all tools from currently connected MCP servers."""
        all_tools = []
        for client in self.clients.values():
            if client.is_connected:
                all_tools.extend(client.tools)
        return all_tools

    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """Formats MCP tools into OpenAI / Ollama standard tool calling schemas."""
        tools_schema = []
        for tool in self.get_all_tools():
            # Namespaced tool name to avoid collisions across servers
            namespaced_name = f"{tool.server_name}__{tool.name}"
            tools_schema.append({
                "type": "function",
                "function": {
                    "name": namespaced_name,
                    "description": f"[{tool.server_name}] {tool.description}",
                    "parameters": tool.input_schema or {"type": "object", "properties": {}}
                }
            })
        return tools_schema

    async def execute_tool(self, namespaced_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes an MCP tool by parsing 'server_name__tool_name'.
        """
        if "__" in namespaced_name:
            server_name, tool_name = namespaced_name.split("__", 1)
        else:
            # Fallback search across connected servers
            server_name = None
            tool_name = namespaced_name
            for s_name, client in self.clients.items():
                if any(t.name == tool_name for t in client.tools):
                    server_name = s_name
                    break

        if not server_name or server_name not in self.clients:
            return {"error": f"MCP server for tool '{namespaced_name}' is not connected"}

        client = self.clients[server_name]
        try:
            res = await client.call_tool(tool_name, arguments)
            return {
                "success": True,
                "server": server_name,
                "tool": tool_name,
                "result": res
            }
        except Exception as e:
            return {
                "success": False,
                "server": server_name,
                "tool": tool_name,
                "error": str(e)
            }

    async def close(self):
        """Disconnects all running servers."""
        for client in self.clients.values():
            await client.disconnect()
        self.clients = {}
