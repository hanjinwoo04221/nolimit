import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.server.routes import router

app = FastAPI(
    title="ContextForge - Infinite Context Local AI Assistant",
    description="Dynamically budgets and injects project snippets and long-term memory into local LLMs without context overflow.",
    version="1.0.0"
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Static files path
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "ui" / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "ContextForge API is running. UI files not yet loaded."}

def run_server(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    uvicorn.run("src.server.app:app", host=host, port=port, reload=False)

if __name__ == "__main__":
    run_server()
