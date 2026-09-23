import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.core.config import config, SystemConfig
from src.core.project_manager import ProjectManager, CodeModificationProposal
from src.core.context_assembler import DialogueTurn
from src.core.llm_client import LocalLLMClient
from src.core.mcp_client import MCPServerConfig

router = APIRouter(prefix="/api")

# Singleton ProjectManager and LLMClient for the session
manager = ProjectManager()
llm_client = LocalLLMClient()

class ProjectSelectRequest(BaseModel):
    project_path: str

class ChatRequest(BaseModel):
    prompt: str
    history: List[Dict[str, str]] = []  # [{"role": "user", "content": ...}]
    session_id: str = "default"
    provider: Optional[str] = None
    model_name: Optional[str] = None
    custom_max_tokens: Optional[int] = None
    temperature: float = 0.3

class ApplyCodeRequest(BaseModel):
    file_path: str
    action: str
    code_content: str

class MCPServerRequest(BaseModel):
    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = []
    env: Dict[str, str] = {}
    url: Optional[str] = None
    enabled: bool = True

class CallMCPToolRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = {}

class PullModelRequest(BaseModel):
    model_name: str

class ReadFileRequest(BaseModel):
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None

class EditFileRequest(BaseModel):
    file_path: str
    content: str

class CreateFileRequest(BaseModel):
    file_path: str
    content: str

class RestoreBackupRequest(BaseModel):
    backup_path: str
    target_path: str

@router.get("/health")
async def get_health():
    health = await llm_client.check_health()
    stats = manager.memory_mgr.get_stats() if manager.memory_mgr else None
    return {
        "status": "online",
        "llm_health": health,
        "active_project": str(manager.project_path) if manager.project_path else None,
        "stats": stats
    }

@router.get("/models")
async def get_models(provider: str = "ollama", base_url: Optional[str] = None):
    models = await llm_client.list_models(provider=provider, base_url=base_url)
    return {"provider": provider, "models": models}

@router.post("/project/select")
async def select_project(req: ProjectSelectRequest):
    p_path = Path(req.project_path).resolve()
    if not p_path.exists() or not p_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.project_path}")
    
    result = manager.set_project(str(p_path))
    return result

@router.post("/project/reindex")
async def reindex_project():
    if not manager.project_path:
        raise HTTPException(status_code=400, detail="No active project selected")
    result = manager.index_project()
    return result

@router.get("/project/stats")
async def get_project_stats():
    if not manager.project_path:
        return {"active": False}
    stats = manager.memory_mgr.get_stats() if manager.memory_mgr else {}
    return {
        "active": True,
        "project_path": str(manager.project_path),
        "project_name": manager.project_path.name,
        "stats": stats
    }

@router.get("/project/file")
async def read_project_file(file_path: str = Query(...)):
    content = manager.read_file_content(file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found or cannot be read")
    return {"file_path": file_path, "content": content}

@router.post("/search")
async def search_memory(query: str = Body(..., embed=True), top_k: int = Body(8, embed=True)):
    if not manager.memory_mgr:
        raise HTTPException(status_code=400, detail="No active project memory")
    
    code_results = manager.memory_mgr.retrieve_relevant_code(query, top_k=top_k)
    mem_results = manager.memory_mgr.retrieve_relevant_memories(query, session_id="default", top_k=4)

    return {
        "code_chunks": [
            {
                "id": c.id,
                "file_path": c.file_path,
                "lines": f"{c.start_line}-{c.end_line}",
                "symbol": c.symbol_name,
                "score": round(score, 4),
                "reason": reason,
                "content": c.content
            }
            for c, score, reason in code_results
        ],
        "episodic_memories": [
            {
                "type": m.memory_type,
                "summary": m.summary,
                "detail": m.detail,
                "score": round(score, 4)
            }
            for m, score in mem_results
        ]
    }

@router.post("/chat/prepare")
async def prepare_chat_context(req: ChatRequest):
    """Inspects the exact context assembled without invoking the LLM."""
    if not manager.project_path:
        raise HTTPException(status_code=400, detail="Please select a project directory first")

    dialogue_history = [
        DialogueTurn(role=m.get("role", "user"), content=m.get("content", ""))
        for m in req.history
    ]

    assembled = manager.prepare_context(
        prompt=req.prompt,
        dialogue_history=dialogue_history,
        session_id=req.session_id,
        custom_max_tokens=req.custom_max_tokens
    )
    return assembled.model_dump()

@router.post("/chat/stream")
async def stream_chat(req: ChatRequest):
    """
    Streams LLM output using Server-Sent Events (SSE).
    Emits metadata first (assembled context & token breakdown), followed by token chunks.
    """
    if not manager.project_path:
        raise HTTPException(status_code=400, detail="Please select and index a project directory first.")

    dialogue_history = [
        DialogueTurn(role=m.get("role", "user"), content=m.get("content", ""))
        for m in req.history
    ]

    # 1. Assemble high-signal budgeted context
    assembled = manager.prepare_context(
        prompt=req.prompt,
        dialogue_history=dialogue_history,
        session_id=req.session_id,
        custom_max_tokens=req.custom_max_tokens
    )

    async def event_generator():
        # Step A: Emit context metadata for the UI Inspector
        meta_event = {
            "type": "context_meta",
            "data": {
                "total_estimated_tokens": assembled.total_estimated_tokens,
                "max_context_budget": assembled.max_context_budget,
                "budget_breakdown": assembled.budget_breakdown,
                "retrieved_chunks": assembled.retrieved_chunks,
                "retrieved_memories": assembled.retrieved_memories,
                "project_total_tokens": assembled.project_total_tokens,
                "compression_ratio": assembled.compression_ratio
            }
        }
        yield f"data: {json.dumps(meta_event, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)

        # Step B: Stream tokens from local LLM
        accumulated_response = []
        builtin_tools = manager.get_builtin_tools_schema()
        mcp_tools = manager.mcp_mgr.get_tools_for_llm() if config.enable_mcp else []
        all_tools = builtin_tools + mcp_tools
        builtin_names = {"read_file", "edit_file", "create_file", "list_dir"}

        try:
            async for chunk in llm_client.stream_chat(
                messages=assembled.messages,
                model_name=req.model_name,
                provider=req.provider,
                temperature=req.temperature,
                tools=all_tools if all_tools else None
            ):
                if isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    for tcall in chunk.get("tool_calls", []):
                        fn = tcall.get("function", {})
                        t_name = fn.get("name", "")
                        t_args = fn.get("arguments", {})
                        if isinstance(t_args, str):
                            try:
                                t_args = json.loads(t_args)
                            except Exception:
                                pass
                        
                        # Emit tool call notification
                        yield f"data: {json.dumps({'type': 'tool_call', 'tool': t_name, 'args': t_args}, ensure_ascii=False)}\n\n"
                        # Execute tool via built-in file operations or MCP
                        if t_name in builtin_names:
                            t_res = manager.execute_builtin_tool(t_name, t_args)
                        else:
                            t_res = await manager.execute_mcp_tool(t_name, t_args)

                        yield f"data: {json.dumps({'type': 'tool_result', 'tool': t_name, 'result': t_res}, ensure_ascii=False)}\n\n"
                elif isinstance(chunk, str):
                    accumulated_response.append(chunk)
                    token_event = {"type": "token", "token": chunk}
                    yield f"data: {json.dumps(token_event, ensure_ascii=False)}\n\n"
        except Exception as e:
            err_event = {"type": "error", "error": str(e)}
            yield f"data: {json.dumps(err_event, ensure_ascii=False)}\n\n"
            return

        full_response = "".join(accumulated_response)

        # Step C: Parse and execute any explicit action blocks in the output
        action_pattern = re.compile(r'```action:(read_file|edit_file|create_file|list_dir)\s*\n(.*?)\n```', re.DOTALL)
        for action_name, action_json_str in action_pattern.findall(full_response):
            try:
                action_args = json.loads(action_json_str.strip())
                yield f"data: {json.dumps({'type': 'tool_call', 'tool': action_name, 'args': action_args}, ensure_ascii=False)}\n\n"
                action_res = manager.execute_builtin_tool(action_name, action_args)
                yield f"data: {json.dumps({'type': 'tool_result', 'tool': action_name, 'result': action_res}, ensure_ascii=False)}\n\n"
            except Exception:
                pass

        # Step D: Record in Long-Term Episodic Memory
        manager.record_turn(req.session_id, req.prompt, full_response)

        # Step E: Detect any code modification proposals
        proposals = manager.extract_code_proposals(full_response)
        if proposals:
            prop_event = {
                "type": "proposals",
                "proposals": [
                    {
                        "file_path": p.file_path,
                        "action": p.action,
                        "code_content": p.code_content,
                        "original_exists": p.original_exists
                    }
                    for p in proposals
                ]
            }
            yield f"data: {json.dumps(prop_event, ensure_ascii=False)}\n\n"

        # Step F: Done event
        done_event = {"type": "done"}
        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/code/apply")
async def apply_code(req: ApplyCodeRequest):
    if not manager.project_path:
        raise HTTPException(status_code=400, detail="No active project")
    
    proposal = CodeModificationProposal(
        file_path=req.file_path,
        action=req.action,
        code_content=req.code_content,
        original_exists=True
    )
    result = manager.apply_code_proposal(proposal)
    return result

@router.get("/memory/recent")
async def get_recent_memories(session_id: str = "default", limit: int = 30):
    if not manager.memory_mgr:
        return {"memories": []}
    mems = manager.memory_mgr.get_recent_memories(session_id=session_id, limit=limit)
    return {
        "memories": [
            {
                "id": m.id,
                "type": m.memory_type,
                "summary": m.summary,
                "detail": m.detail,
                "timestamp": m.timestamp
            }
            for m in mems
        ]
    }

@router.post("/memory/clear")
async def clear_memory(session_id: str = Body("default", embed=True)):
    if manager.memory_mgr:
        manager.memory_mgr.clear_session(session_id)
    return {"success": True}

# --- MCP (Model Context Protocol) Endpoints ---

@router.get("/mcp/servers")
async def get_mcp_servers():
    """Returns all registered MCP servers and their active connection statuses."""
    return await manager.get_mcp_servers()

@router.post("/mcp/server")
async def add_or_update_mcp_server(req: MCPServerRequest):
    """Registers and establishes connection with an MCP server."""
    cfg = MCPServerConfig(
        name=req.name,
        transport=req.transport,
        command=req.command,
        args=req.args,
        env=req.env,
        url=req.url,
        enabled=req.enabled
    )
    ok, msg = await manager.add_mcp_server(cfg)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.delete("/mcp/server")
async def delete_mcp_server(name: str = Query(...)):
    """Removes and disconnects an MCP server."""
    ok = await manager.remove_mcp_server(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    return {"success": True}

@router.get("/mcp/tools")
async def get_mcp_tools():
    """Lists all available tools across connected MCP servers."""
    return {"tools": manager.get_mcp_tools()}

@router.post("/mcp/tool/call")
async def call_mcp_tool(req: CallMCPToolRequest):
    """Manually invokes an MCP tool for testing."""
    result = await manager.execute_mcp_tool(req.tool_name, req.arguments)
    return result

# --- Model Pull & Diagnostics Endpoints ---

@router.post("/models/pull")
async def pull_model_endpoint(req: PullModelRequest):
    """Streams Ollama model download progress via SSE."""
    async def progress_generator():
        async for progress in llm_client.pull_model(req.model_name):
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"
        yield "data: {\"status\": \"completed\"}\n\n"

    return StreamingResponse(progress_generator(), media_type="text/event-stream")

# --- Project File Operations Endpoints ---

@router.get("/file/tree")
async def get_file_tree():
    """Returns flat file tree for the project explorer."""
    if not manager.project_path:
        return {"tree": []}
    return {"tree": manager.get_project_file_tree()}

@router.post("/file/read")
async def read_file_endpoint(req: ReadFileRequest):
    """Reads project file content."""
    res = manager.read_file_tool(req.file_path, req.start_line, req.end_line)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@router.post("/file/edit")
async def edit_file_endpoint(req: EditFileRequest):
    """Edits a project file with automatic backup."""
    res = manager.edit_file_tool(req.file_path, req.content)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@router.post("/file/create")
async def create_file_endpoint(req: CreateFileRequest):
    """Creates a new project file."""
    res = manager.create_file_tool(req.file_path, req.content)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@router.post("/file/restore")
async def restore_file_endpoint(req: RestoreBackupRequest):
    """Restores a file from a backup."""
    res = manager.restore_backup(req.backup_path, req.target_path)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res
