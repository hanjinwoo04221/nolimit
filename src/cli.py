import os
import sys
import argparse
import asyncio
from pathlib import Path

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
from src.core.config import config
from src.core.project_manager import ProjectManager
from src.core.context_assembler import DialogueTurn

async def run_cli():
    parser = argparse.ArgumentParser(description="ContextForge - Infinite Context Local AI Assistant CLI")
    parser.add_argument("--project", "-p", type=str, default=".", help="Project directory path")
    parser.add_argument("--model", "-m", type=str, default=None, help="Model name (e.g. qwen2.5-coder:7b)")
    parser.add_argument("--provider", type=str, default="ollama", choices=["ollama", "openai_compatible"], help="LLM Provider")
    parser.add_argument("--context-limit", "-c", type=int, default=4096, help="Context window token limit (default: 4096)")
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    print("=" * 70)
    print("🧠 ContextForge | 무한 컨텍스트 로컬 AI 어시스턴트 (CLI 모드)")
    print("=" * 70)
    print(f"📁 대상 프로젝트: {project_dir}")
    print(f"🤖 모델 엔진: {args.provider} (한도: {args.context_limit} 토큰)")

    manager = ProjectManager()
    try:
        res = manager.set_project(str(project_dir))
        stats = res.get("stats", {})
        print(f"✅ 프로젝트 색인 완료: {stats.get('total_files', 0)}개 파일, {stats.get('total_chunks', 0)}개 청크 (~{stats.get('total_tokens', 0):,} 토큰)")
    except Exception as e:
        print(f"❌ 프로젝트 색인 실패: {e}")
        return

    # Check model
    models = await manager.llm_client.list_models(provider=args.provider)
    model_name = args.model
    if not model_name:
        if models:
            model_name = models[0]
            print(f"🔍 감지된 로컬 모델 자동 선택: {model_name}")
        else:
            model_name = "qwen2.5-coder:7b"
            print(f"⚠️ 감지된 모델이 없어 기본 모델 지정: {model_name}")

    dialogue_history = []
    session_id = "cli_session"

    print("\n명령어 안내:")
    print(" - 일반 질문 입력 시: 관련 코드만 골라 AI에게 주입 후 스트리밍 답변")
    print(" - /search <검색어>: 프로젝트 LTM 장기 기억 수동 검색")
    print(" - /repo: 프로젝트 디렉토리 구조도 출력")
    print(" - exit / quit: 종료")
    print("-" * 70)

    while True:
        try:
            user_input = input("\n👤 질문 (또는 명령어) > ").strip()
            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "q"]:
                print("👋 ContextForge를 종료합니다.")
                break

            if user_input.startswith("/search "):
                query = user_input[8:].strip()
                results = manager.memory_mgr.retrieve_relevant_code(query, top_k=5)
                print(f"\n🔍 [검색 결과] '{query}'")
                for c, score, reason in results:
                    print(f"  • {c.file_path}:{c.start_line}-{c.end_line} (점수: {round(score, 3)}) [{reason}]")
                continue

            if user_input == "/repo":
                _, repo_map = manager.memory_mgr.load_project_chunks()
                print(f"\n🗺️ [프로젝트 구조도]\n{repo_map}")
                continue

            # 1. Assemble dynamic context
            assembled = manager.prepare_context(
                prompt=user_input,
                dialogue_history=dialogue_history,
                session_id=session_id,
                custom_max_tokens=args.context_limit
            )

            chunk_count = len(assembled.retrieved_chunks)
            tok_used = assembled.total_estimated_tokens
            print(f"\n⚡ [컨텍스트 최적화] 주입된 코드 청크 {chunk_count}개 | 사용 토큰: ~{tok_used:,} / {args.context_limit:,} (압축률 {assembled.compression_ratio}%)")
            print(f"🤖 {model_name} 응답 생성 중...\n" + "-" * 50)

            # 2. Stream tokens
            accumulated = []
            async for token in manager.llm_client.stream_chat(
                messages=assembled.messages,
                model_name=model_name,
                provider=args.provider
            ):
                sys.stdout.write(token)
                sys.stdout.flush()
                accumulated.append(token)

            full_resp = "".join(accumulated)
            print("\n" + "-" * 50)

            # Record turn
            manager.record_turn(session_id, user_input, full_resp)
            dialogue_history.append(DialogueTurn(role="user", content=user_input))
            dialogue_history.append(DialogueTurn(role="assistant", content=full_resp))

            # Check proposals
            proposals = manager.extract_code_proposals(full_resp)
            if proposals:
                print(f"\n💡 [코드 변경 제안 감지] {len(proposals)}개의 파일 수정 제안이 있습니다.")
                for p in proposals:
                    ans = input(f"   '{p.file_path}' ({p.action}) 파일에 적용하시겠습니까? (y/N): ").strip().lower()
                    if ans == 'y':
                        apply_res = manager.apply_code_proposal(p)
                        print(f"   ✅ 적용 완료! (백업: {apply_res.get('backup_created', '없음')})")

        except (KeyboardInterrupt, EOFError):
            print("\n👋 종료합니다.")
            break
        except Exception as e:
            print(f"\n❌ 오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(run_cli())
