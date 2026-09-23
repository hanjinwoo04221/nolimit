import sys
import os
import subprocess
import webbrowser
import threading
import time
from pathlib import Path

# Configure console encoding for Windows to prevent cp949 UnicodeEncodeError
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Ensure dependencies are available, or auto-switch to .venv
try:
    import uvicorn
    import fastapi
except ImportError:
    venv_python = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists() and sys.executable.lower() != str(venv_python).lower():
        print(f"[ContextForge] 가상환경(.venv)으로 자동 전환하여 실행합니다...")
        subprocess.run([str(venv_python)] + sys.argv)
        sys.exit(0)
    else:
        print("[ContextForge] uvicorn 또는 필수 패키지가 설치되지 않았습니다.")
        print("[ContextForge] 패키지를 설치하는 중입니다: pip install -r requirements.txt")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT_DIR / "requirements.txt")])
        import uvicorn
        import fastapi

from src.server.app import app

def open_browser():
    time.sleep(1.2)
    url = "http://localhost:8765"
    try:
        print(f"[ContextForge] 브라우저에서 대시보드를 엽니다: {url}")
        webbrowser.open(url)
    except Exception:
        pass

if __name__ == "__main__":
    print("=" * 65)
    print("[ContextForge] 무한 컨텍스트 로컬 AI 프로젝트 어시스턴트")
    print("=" * 65)
    print(">> 대시보드 주소: http://localhost:8765")
    print(">> 로컬 Ollama (http://localhost:11434) 또는 LM Studio (http://localhost:1234/v1)")
    print("=" * 65)

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("src.server.app:app", host="127.0.0.1", port=8765, log_level="info")

