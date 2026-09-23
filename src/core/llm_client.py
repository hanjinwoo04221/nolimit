import json
import httpx
from typing import AsyncGenerator, List, Dict, Any, Optional
from src.core.config import config, SystemConfig

class LocalLLMClient:
    """
    Unified client for communicating with local LLM runtimes (Ollama and OpenAI-compatible).
    Supports streaming generation, model discovery, and health checks.
    """
    def __init__(self, sys_config: Optional[SystemConfig] = None):
        self.config = sys_config or config

    async def list_models(self, provider: Optional[str] = None, base_url: Optional[str] = None) -> List[str]:
        """Discovers available local models from the selected provider."""
        provider = provider or self.config.provider
        models = []

        if provider == "ollama":
            url = f"{base_url or self.config.ollama_url}/api/tags"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m["name"] for m in data.get("models", [])]
            except Exception:
                pass
        else:
            # OpenAI compatible (LM Studio / vLLM)
            url = f"{base_url or self.config.openai_url}/models"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(url, headers={"Authorization": f"Bearer {self.config.openai_api_key}"})
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m["id"] for m in data.get("data", [])]
            except Exception:
                pass

        return models

    async def check_health(self, provider: Optional[str] = None, base_url: Optional[str] = None) -> Dict[str, Any]:
        """Checks connection to the local LLM server."""
        provider = provider or self.config.provider
        models = await self.list_models(provider=provider, base_url=base_url)
        return {
            "provider": provider,
            "connected": len(models) > 0 or await self._ping_server(provider, base_url),
            "available_models": models
        }

    async def _ping_server(self, provider: str, base_url: Optional[str]) -> bool:
        try:
            target = base_url or (self.config.ollama_url if provider == "ollama" else self.config.openai_url)
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(target)
                return resp.status_code in [200, 404]
        except Exception:
            return False

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.3,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Any, None]:
        """
        Streams response tokens or tool call events from the local LLM runtime.
        """
        provider = provider or self.config.provider
        model = model_name or self.config.model_name

        if provider == "ollama":
            url = f"{base_url or self.config.ollama_url}/api/chat"
            payload: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_ctx": self.config.max_context_tokens
                }
            }
            if tools:
                payload["tools"] = tools

            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream("POST", url, json=payload) as response:
                        if response.status_code == 404:
                            yield (
                                f"\n\n> [!WARNING]\n"
                                f"> **로컬 모델 '{model}'이 아직 Ollama에 다운로드되지 않았습니다.**\n\n"
                                f"웹 대시보드 좌측 상단의 **[모델 다운로드]** 버튼을 클릭하거나, "
                                f"명령 프롬프트/터미널에서 아래 명령을 실행해주세요:\n\n"
                                f"```bash\n"
                                f"ollama pull {model}\n"
                                f"```\n\n"
                                f"*(💡 용량이 작고 빠른 코딩 모델: `ollama pull qwen2.5-coder:1.5b` 추천)*"
                            )
                            return
                        elif response.status_code != 200:
                            err_body = await response.aread()
                            yield f"\n[Ollama Error: Status {response.status_code} - {err_body.decode('utf-8', errors='ignore')}]"
                            return

                        async for line in response.aiter_lines():
                            if line.strip():
                                try:
                                    chunk = json.loads(line)
                                    if not isinstance(chunk, dict):
                                        continue
                                    msg = chunk.get("message", {})
                                    if isinstance(msg, dict):
                                        if msg.get("tool_calls"):
                                            yield {"type": "tool_call", "tool_calls": msg["tool_calls"]}
                                        content = msg.get("content", "")
                                    elif isinstance(msg, str):
                                        content = msg
                                    else:
                                        content = chunk.get("response", "")

                                    if content:
                                        yield content
                                    if chunk.get("done", False):
                                        break
                                except json.JSONDecodeError:
                                    continue
            except httpx.ConnectError:
                yield (
                    "\n\n> [!CAUTION]\n"
                    "> **로컬 Ollama 서버에 연결할 수 없습니다.**\n\n"
                    "Ollama 데스크톱 앱이 켜져 있는지 확인하거나, 터미널에서 `ollama serve`를 실행해주세요."
                )
            except Exception as e:
                yield f"\n[연결 오류: {str(e)}]"

        else:
            # OpenAI Compatible (LM Studio / vLLM)
            url = f"{base_url or self.config.openai_url}/chat/completions"
            payload: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "temperature": temperature,
                "max_tokens": self.config.max_output_tokens
            }
            if tools:
                payload["tools"] = tools

            headers = {
                "Authorization": f"Bearer {self.config.openai_api_key}",
                "Content-Type": "application/json"
            }

            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as response:
                        if response.status_code != 200:
                            err_body = await response.aread()
                            yield f"\n[OpenAI-Compatible Server Error: {response.status_code} - {err_body.decode('utf-8', errors='ignore')}]"
                            return

                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                if not isinstance(chunk, dict):
                                    continue
                                choices = chunk.get("choices", [])
                                if isinstance(choices, list) and choices:
                                    first_choice = choices[0]
                                    if isinstance(first_choice, dict):
                                        delta = first_choice.get("delta", {})
                                        if isinstance(delta, dict):
                                            if delta.get("tool_calls"):
                                                yield {"type": "tool_call", "tool_calls": delta["tool_calls"]}
                                            content = delta.get("content", "")
                                            if content:
                                                yield content
                                        elif isinstance(delta, str) and delta:
                                            yield delta

                                        msg = first_choice.get("message", {})
                                        if isinstance(msg, dict):
                                            if msg.get("tool_calls"):
                                                yield {"type": "tool_call", "tool_calls": msg["tool_calls"]}
                                            content = msg.get("content", "")
                                            if content:
                                                yield content
                            except json.JSONDecodeError:
                                continue
            except httpx.ConnectError:
                yield (
                    f"\n[⚠️ 로컬 OpenAI 호환 서버({url})에 연결할 수 없습니다. "
                    "LM Studio나 vLLM 서버가 켜져 있는지 확인해주세요.]"
                )
            except Exception as e:
                yield f"\n[연결 오류: {str(e)}]"

    async def pull_model(self, model_name: str, base_url: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Streams Ollama model download progress."""
        url = f"{base_url or self.config.ollama_url}/api/pull"
        try:
            async with httpx.AsyncClient(timeout=1800.0) as client:
                async with client.stream("POST", url, json={"name": model_name, "stream": True}) as response:
                    if response.status_code != 200:
                        yield {"status": "error", "error": f"Ollama HTTP {response.status_code}"}
                        return
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                yield data
                            except Exception:
                                continue
        except Exception as e:
            yield {"status": "error", "error": str(e)}

