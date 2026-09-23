# 🧠 ContextForge (컨텍스트포지)
### 로컬 AI 모델을 위한 무한 컨텍스트(Infinite Context) 프로젝트 어시스턴트

> **"프로젝트 전체가 아무리 방대해도, 로컬 AI의 작은 컨텍스트(4k~8k) 제한 없이 자유롭게 활용하세요!"**

---

## 🌟 개요 (Overview)

로컬 AI 모델(Ollama의 `qwen2.5-coder`, `llama3.2`, LM Studio 등)은 GPU VRAM 및 모델 아키텍처 특성상 **컨텍스트 길이(Context Length, 4k~8k 토큰)**에 엄격한 제한이 있습니다.
수십~수백 개의 파일과 수십만 토큰으로 이루어진 실제 소프트웨어 프로젝트를 로컬 AI에 그대로 넣으면 **OOM(메모리 부족), 토큰 처리 속도 급감, 환각(Lost-in-the-Middle) 현상**이 발생합니다.

**ContextForge**는 이러한 한계를 극복하기 위해 개발된 시스템입니다:
1. 프로젝트 전체 코드와 과거 대화 이력을 **장기 기억 장치(Long-Term Memory, SQLite + 하이브리드 검색 인덱스)**에 안전하게 보관합니다.
2. 사용자의 질문과 최근 대화 흐름을 분석하여, **현재 행동에 꼭 필요한 핵심 코드 조각과 과거 결정 사항만을 동적으로 선별(Dynamic Context Assembler)**합니다.
3. 로컬 AI 모델의 컨텍스트 예산(예: 4,096 토큰)을 초과하지 않는 고밀도(High-Signal) 프롬프트를 구성해 로컬 AI에게 주입함으로써, **컨텍스트 길이의 한계를 사실상 없앤 상태로 로컬 AI를 사용할 수 있게 합니다.**

---

## 🏗️ 핵심 아키텍처 (Key Architecture)

```
[사용자 질문 / 대화]
         │
         ▼
[동적 컨텍스트 조립기 (Dynamic Context Assembler)]
 ├── 1. 질문 의도 분석 및 키워드/심볼 확장
 ├── 2. 엄격한 토큰 예산제 운용 (예: 4,096 토큰 슬라이더)
 ├── 3. 장기 기억 장치(LTM)에서 핵심 지식 검색
 │        ├── [프로젝트 코드베이스 LTM] (하이브리드 BM25 + 벡터 검색)
 │        └── [에피소드 대화/결정 LTM] (과거 수정 이력, 규칙, 결정 사항)
 └── 4. 시스템 지침 + 저장소 구조도 + 선별된 코드 + 최근 대화 결합
         │
         ▼ (고밀도 고효율 컨텍스트 창 주입)
[로컬 AI 모델 (Ollama / LM Studio)] ───► [실시간 스트리밍 답변 생성]
         │
         └──► [코드 수정 제안 감지 시 1-클릭 실제 파일 반영 (자동 백업 지원)]
```

### 1. 장기 기억 장치 (Long-Term Memory)
- **지능형 소스 코드 청킹 (Smart Chunker)**: 함수(`def`, `function`, `fn`), 클래스(`class`), 마크다운 헤더 경계를 인식하여 의미 단위로 청킹.
- **하이브리드 랭킹 (BM25 + Semantic Vector + RRF)**: 정확한 함수명/변수명 일치는 BM25로, 자연어 개념 질문은 벡터 코사인 유사도로 결합 검색.
- **SQLite 영구 보관 (`.context_memory/memory.db`)**: 프로젝트 내에 로컬 DB로 저장되어 앱을 재시작해도 즉시 로드.
- **에피소드 기억 (Episodic Memory)**: 이전 수십~수백 턴 전의 대화 및 핵심 설계 결정 사항을 메모리 카드로 보관하여 회상.

### 2. 동적 컨텍스트 조립기 (Dynamic Context Budgeter)
- 사용자가 설정한 로컬 AI의 컨텍스트 한도(2k, 4k, 8k, 16k, 32k)를 **1토큰도 넘지 않도록 철저히 관리**:
  - 시스템 페르소나 및 지침: ~12%
  - 프로젝트 아키텍처 뼈대(Repo Map): ~10%
  - 선별된 핵심 코드 청크: ~48%
  - 회상된 과거 기억/결정: ~10%
  - 최근 대화 기록(단기 기억 2~4턴): ~20%
- 압축률 메트릭: 대규모 프로젝트(예: 15만 토큰) 중 필요한 2천 토큰만 골라 주입하여 **98% 이상의 컨텍스트 절약 달성**.

### 3. 직관적인 웹 대시보드 & Context Inspector
- **Context Inspector (AI가 실제로 본 컨텍스트)**: AI에게 전달된 프롬프트와 참조된 코드 청크(파일, 라인, 매칭 점수, 이유)를 실시간 투명 공개.
- **코드 자동 반영 (Apply to Project)**: AI가 코드 수정을 제안한 경우, 버튼 클릭 한 번으로 실제 프로젝트 파일에 반영 (기존 파일은 `.bak_YYYYMMDD_HHMMSS`로 자동 백업).

### 4. 표준 MCP (Model Context Protocol) 연동
- **오픈소스 MCP 생태계 지원**: `mcp-server-fetch` (웹 페이지 검색), `mcp-server-git` (버전 관리), `mcp-server-sqlite` 등 표준 `mcp_servers.json` 규격 완벽 호환.
- **`stdio` 및 `sse` 전송**: 로컬 CLI 명령어 실행 및 원격 HTTP SSE 서버 지원.
- **로컬 AI 도구 호출 루프**: 로컬 AI(Ollama / LM Studio)가 스스로 필요한 MCP 도구를 호출하고, 실행 결과를 바탕으로 정확한 답변 생성.
- **대시보드 실시간 관리**: 서버 추가/삭제, 사용 가능한 도구 목록 및 파라미터 확인, 즉시 테스트 실행 지원.

---

## 🚀 빠른 시작 가이드 (Quick Start)

### 사전 준비 (Prerequisites)
1. **Python 3.10 이상** 설치
2. **로컬 AI 런타임** (둘 중 하나 권장):
   - **Ollama**: [https://ollama.com](https://ollama.com) 설치 후 원하는 모델 다운로드:
     ```bash
     ollama run qwen2.5-coder:7b
     # 또는
     ollama run llama3.2:3b
     ```
   - **LM Studio**: 로컬 추론 서버 켜기 (`http://localhost:1234/v1`)

---

### 방법 1. 윈도우 원클릭 실행 (가장 간편한 방법)
프로젝트 폴더 내의 **`run.bat`** (또는 PowerShell용 `run.ps1`)을 더블 클릭합니다.
- 가상환경(`venv`) 생성 및 필수 패키지 설치가 자동으로 진행됩니다.
- 서버가 실행되면서 웹 브라우저(`http://localhost:8765`)가 자동으로 열립니다!

```cmd
run.bat
```

---

### 방법 2. 수동 실행 (터미널)
```bash
# 1. 가상환경 생성 및 활성화
uv venv .venv
.\.venv\Scripts\activate

# 2. 필수 라이브러리 설치
pip install -r requirements.txt

# 3. ContextForge 웹 대시보드 실행
python main.py
```
브라우저에서 `http://localhost:8765` 로 접속합니다.

---

### 방법 3. CLI (터미널) 대화 모드
웹 브라우저 없이 터미널 안에서 가볍게 작업하고 싶을 때:
```bash
python -m src.cli --project "C:\내프로젝트경로" --model "qwen2.5-coder:7b" --context-limit 4096
```

---

## 🖥️ 사용 방법 (Usage Guide)

1. **프로젝트 선택**:
   - 좌측 상단 입력창에 분석하고자 하는 프로젝트의 절대 경로(예: `C:\MyProject`)를 입력하고 화살표 버튼을 누릅니다.
   - 프로젝트가 즉시 스캔되며 파일 수, 코드 청크 수, 전체 토큰 수가 표시됩니다.
2. **로컬 모델 선택**:
   - Ollama 또는 OpenAI 호환(LM Studio)을 선택합니다.
   - PC에 설치된 모델이 드롭다운에 자동으로 표시됩니다.
   - 사용 중인 GPU 메모리에 맞춰 **컨텍스트 한도(Context Limit)** 슬라이더(예: 4,096 토큰)를 조절합니다.
3. **질문 및 대화**:
   - 하단 대화창에 프로젝트 관련 질문을 입력합니다. (예: *"이 프로젝트의 로그인 로직이 어떻게 흘러가는지 설명해줘."*)
   - 우측의 **컨텍스트 인스펙터**에서 어떤 코드 청크가 선별되었는지, 토큰 예산이 어떻게 분배되었는지 실시간으로 확인합니다.
4. **코드 변경 반영**:
   - AI가 코드 수정을 제안하면 메시지 하단에 **"프로젝트에 코드 반영 (Apply)"** 버튼이 활성화됩니다.
   - 클릭 시 파일이 자동 수정되고, 수정 전 파일은 `.bak`으로 안전하게 백업됩니다.
5. **장기 기억 검색 (LTM Search)**:
   - 우측 두 번째 탭에서 특정 함수나 변수명을 직접 검색하여 색인된 내용을 열람할 수 있습니다.

---

## 🧪 테스트 실행 (Running Tests)

시스템의 모든 기능(청커, 검색 엔진, 메모리 매니저, 컨텍스트 조립기, REST API)에 대한 단위/통합 테스트가 포함되어 있습니다:

```bash
.\.venv\Scripts\python.exe -m unittest discover tests
```

---

## 📁 디렉토리 구조 (Folder Structure)

```
새 폴더 (3)/
├── main.py                     # 웹 애플리케이션 진입점 (자동 브라우저 실행)
├── run.bat                     # 윈도우 원클릭 배치 실행기
├── run.ps1                     # 파워셸 실행기
├── requirements.txt            # 파이썬 종속성 목록
├── README.md                   # 프로젝트 사용 설명서
├── src/
│   ├── cli.py                  # 대화형 터미널 CLI 도구
│   ├── core/
│   │   ├── config.py           # 시스템 설정 및 토큰 비율 정의
│   │   ├── chunker.py          # 지능형 AST/함수/클래스 코드 청커
│   │   ├── indexer.py          # 파일 스캐너 및 저장소 구조도 생성기
│   │   ├── search.py           # BM25 + 벡터 하이브리드 검색 엔진
│   │   ├── memory.py           # SQLite 기반 장기 기억(LTM) 및 에피소드 관리
│   │   ├── context_assembler.py# 동적 컨텍스트 조립기 & 토큰 예산 관리자
│   │   ├── llm_client.py       # Ollama 및 OpenAI 호환 로컬 LLM 스트리밍 클라이언트
│   │   └── project_manager.py  # 프로젝트 총괄 관리자 (수정/백업/검색)
│   ├── server/
│   │   ├── app.py              # FastAPI 서버 인스턴스
│   │   └── routes.py           # REST API 및 SSE 스트리밍 엔드포인트
│   └── ui/
│       └── static/
│           ├── index.html      # 모던 다크 테마 대시보드
│           ├── style.css       # 글래스모피즘 & 개발자 UI 스타일
│           └── app.js          # 실시간 SSE 스트리밍 & 컨텍스트 시각화 로직
└── tests/
    ├── test_chunker.py         # 청킹 및 심볼 감지 테스트
    ├── test_search.py          # 하이브리드 검색 및 랭킹 테스트
    ├── test_memory_and_assembler.py # 장기 기억 및 예산 한도 테스트
    └── test_api_integration.py # FastAPI 엔드포인트 통합 테스트
```

---

## 🛡️ 라이선스 (License)
MIT License. 자유롭게 수정 및 배포하실 수 있습니다.
