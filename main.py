import sys
import webbrowser
import threading
import time
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

import uvicorn
from src.server.app import app

def open_browser():
    time.sleep(1.2)
    url = "http://localhost:8765"
    print(f"🚀 브라우저에서 ContextForge 대시보드를 엽니다: {url}")
    webbrowser.open(url)

if __name__ == "__main__":
    print("=" * 65)
    print("🧠 ContextForge | 무한 컨텍스트 로컬 AI 프로젝트 어시스턴트")
    print("=" * 65)
    print("🌐 대시보드 주소: http://localhost:8765")
    print("⚡ 로컬 Ollama (http://localhost:11434) 또는 LM Studio (http://localhost:1234/v1)")
    print("=" * 65)

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("src.server.app:app", host="127.0.0.1", port=8765, log_level="info")
