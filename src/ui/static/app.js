// ContextForge Web Application Logic

let activeProject = null;
let conversationHistory = [];
const sessionId = "session_" + Math.random().toString(36).substring(2, 9);
let isStreaming = false;

// DOM Elements
const projectPathInput = document.getElementById("project-path-input");
const loadProjectBtn = document.getElementById("load-project-btn");
const reindexBtn = document.getElementById("reindex-btn");
const viewRepoMapBtn = document.getElementById("view-repo-map-btn");
const projectInfoBox = document.getElementById("project-info-box");
const activeProjectBadge = document.getElementById("active-project-badge");

const statFiles = document.getElementById("stat-files");
const statChunks = document.getElementById("stat-chunks");
const statTokens = document.getElementById("stat-tokens");

const providerSelect = document.getElementById("provider-select");
const modelSelect = document.getElementById("model-select");
const customModelInput = document.getElementById("custom-model-input");
const refreshModelsBtn = document.getElementById("refresh-models-btn");
const contextLimitSlider = document.getElementById("context-limit-slider");
const contextLimitDisplay = document.getElementById("context-limit-display");
const tempSlider = document.getElementById("temp-slider");
const tempDisplay = document.getElementById("temp-display");

const chatMessages = document.getElementById("chat-messages");
const promptInput = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");
const streamStatus = document.getElementById("stream-status");
const clearChatBtn = document.getElementById("clear-chat-btn");
const clearMemoryBtn = document.getElementById("clear-memory-btn");
const quickSuggestions = document.getElementById("quick-suggestions");

const llmStatusBadge = document.getElementById("llm-status-badge");
const toggleInspectorBtn = document.getElementById("toggle-inspector-btn");
const inspectorPanel = document.getElementById("inspector-panel");

// Inspector elements
const barSystem = document.getElementById("bar-system");
const barRepo = document.getElementById("bar-repo");
const barCode = document.getElementById("bar-code");
const barMemory = document.getElementById("bar-memory");
const barDialogue = document.getElementById("bar-dialogue");
const compressionRate = document.getElementById("compression-rate");
const injectedChunksList = document.getElementById("injected-chunks-list");
const injectedMemoriesList = document.getElementById("injected-memories-list");
const injectedChunkCount = document.getElementById("injected-chunk-count");
const injectedMemoryCount = document.getElementById("injected-memory-count");

// Search & Episode tabs
const ltmSearchInput = document.getElementById("ltm-search-input");
const ltmSearchBtn = document.getElementById("ltm-search-btn");
const ltmSearchResults = document.getElementById("ltm-search-results");
const episodesTimelineList = document.getElementById("episodes-timeline-list");
const refreshEpisodesBtn = document.getElementById("refresh-episodes-btn");

// MCP elements
const mcpStatusBadge = document.getElementById("mcp-status-badge");
const mcpStatusText = document.getElementById("mcp-status-text");
const refreshMcpBtn = document.getElementById("refresh-mcp-btn");
const mcpServersList = document.getElementById("mcp-servers-list");
const mcpToolsList = document.getElementById("mcp-tools-list");
const mcpToolsCountBadge = document.getElementById("mcp-tools-count-badge");
const mcpNameInput = document.getElementById("mcp-name-input");
const mcpTransportSelect = document.getElementById("mcp-transport-select");
const mcpCommandInput = document.getElementById("mcp-command-input");
const mcpArgsInput = document.getElementById("mcp-args-input");
const mcpUrlInput = document.getElementById("mcp-url-input");
const mcpStdioFields = document.getElementById("mcp-stdio-fields");
const mcpSseFields = document.getElementById("mcp-sse-fields");
const addMcpServerBtn = document.getElementById("add-mcp-server-btn");

// Model Pull elements
const pullModelNameInput = document.getElementById("pull-model-name-input");
const pullModelBtn = document.getElementById("pull-model-btn");
const pullProgressContainer = document.getElementById("pull-progress-container");
const pullProgressBar = document.getElementById("pull-progress-bar");
const pullStatusText = document.getElementById("pull-status-text");

// File Explorer & Editor elements
const refreshFilesBtn = document.getElementById("refresh-files-btn");
const newFileBtn = document.getElementById("new-file-btn");
const fileTreeContainer = document.getElementById("file-tree-container");
const fileEditorSection = document.getElementById("file-editor-section");
const activeFilePath = document.getElementById("active-file-path");
const saveFileBtn = document.getElementById("save-file-btn");
const closeEditorBtn = document.getElementById("close-editor-btn");
const fileEditorContent = document.getElementById("file-editor-content");
const fileEditorStatus = document.getElementById("file-editor-status");
let currentEditingPath = null;

// Modal elements
const repoModal = document.getElementById("repo-modal");
const repoMapContent = document.getElementById("repo-map-content");
const modalCloseBtn = document.querySelector(".modal-close-btn");

// Initialization
document.addEventListener("DOMContentLoaded", () => {
    initEvents();
    checkHealthAndModels();
    autoPopulateCurrentDirectory();
    loadMCPServers();
});

function initEvents() {
    // Sliders
    contextLimitSlider.addEventListener("input", (e) => {
        contextLimitDisplay.textContent = Number(e.target.value).toLocaleString() + " 토큰";
    });

    tempSlider.addEventListener("input", (e) => {
        tempDisplay.textContent = e.target.value;
    });

    // Provider change
    providerSelect.addEventListener("change", () => {
        fetchModels();
    });

    refreshModelsBtn.addEventListener("click", () => {
        fetchModels();
    });

    // Project Actions
    loadProjectBtn.addEventListener("click", handleSelectProject);
    projectPathInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") handleSelectProject();
    });

    reindexBtn.addEventListener("click", handleReindex);
    viewRepoMapBtn.addEventListener("click", showRepoMapModal);

    // Modal
    modalCloseBtn.addEventListener("click", () => repoModal.classList.remove("active"));
    window.addEventListener("click", (e) => {
        if (e.target === repoModal) repoModal.classList.remove("active");
    });

    // Chat Actions
    sendBtn.addEventListener("click", sendMessage);
    promptInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    promptInput.addEventListener("input", () => {
        sendBtn.disabled = !promptInput.value.trim() || isStreaming;
    });

    clearChatBtn.addEventListener("click", () => {
        chatMessages.innerHTML = "";
        conversationHistory = [];
    });

    clearMemoryBtn.addEventListener("click", handleClearMemory);

    // Toggle Inspector
    toggleInspectorBtn.addEventListener("click", () => {
        inspectorPanel.classList.toggle("hidden");
    });

    // Tabs
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(btn.dataset.tab).classList.add("active");
            if (btn.dataset.tab === "tab-files") {
                loadFileTree();
            }
        });
    });

    // LTM Search
    ltmSearchBtn.addEventListener("click", handleLtmSearch);
    ltmSearchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") handleLtmSearch();
    });

    // Episodes refresh
    refreshEpisodesBtn.addEventListener("click", loadEpisodes);

    // MCP Listeners
    if (refreshMcpBtn) refreshMcpBtn.addEventListener("click", loadMCPServers);
    if (mcpTransportSelect) {
        mcpTransportSelect.addEventListener("change", () => {
            const isStdio = mcpTransportSelect.value === "stdio";
            mcpStdioFields.style.display = isStdio ? "block" : "none";
            mcpSseFields.style.display = isStdio ? "none" : "block";
        });
    }
    if (addMcpServerBtn) addMcpServerBtn.addEventListener("click", handleAddMCPServer);

    // Model Pull Listeners
    if (pullModelBtn) pullModelBtn.addEventListener("click", handlePullModel);
    document.querySelectorAll(".quick-pull-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            if (pullModelNameInput) {
                pullModelNameInput.value = chip.dataset.model;
                handlePullModel();
            }
        });
    });

    // File Explorer Listeners
    if (refreshFilesBtn) refreshFilesBtn.addEventListener("click", loadFileTree);
    if (newFileBtn) newFileBtn.addEventListener("click", handleCreateNewFile);
    if (saveFileBtn) saveFileBtn.addEventListener("click", handleSaveFile);
    if (closeEditorBtn) closeEditorBtn.addEventListener("click", () => {
        if (fileEditorSection) fileEditorSection.style.display = "none";
        currentEditingPath = null;
        document.querySelectorAll(".tree-item").forEach(r => r.classList.remove("selected"));
    });

    // Suggestions
    quickSuggestions.addEventListener("click", (e) => {
        const chip = e.target.closest(".suggestion-chip");
        if (chip && chip.dataset.prompt) {
            promptInput.value = chip.dataset.prompt;
            promptInput.focus();
            sendBtn.disabled = false;
        }
    });
}

async function autoPopulateCurrentDirectory() {
    // Check if backend already has active project or use default
    try {
        const res = await fetch("/api/project/stats");
        const data = await res.json();
        if (data.active) {
            updateProjectUI(data);
        }
    } catch (e) {
        console.warn("Could not fetch current project stats", e);
    }
}

async function checkHealthAndModels() {
    try {
        const res = await fetch("/api/health");
        const data = await res.json();
        const llm = data.llm_health;

        if (llm.connected) {
            llmStatusBadge.className = "status-indicator online";
            llmStatusBadge.querySelector(".status-text").textContent = `로컬 LLM 연결됨 (${llm.provider})`;
        } else {
            llmStatusBadge.className = "status-indicator offline";
            llmStatusBadge.querySelector(".status-text").textContent = "로컬 LLM 미감지 (Ollama 확인 필요)";
        }

        await fetchModels();
    } catch (e) {
        llmStatusBadge.className = "status-indicator offline";
        llmStatusBadge.querySelector(".status-text").textContent = "서버 연결 불가";
    }
}

async function fetchModels() {
    const provider = providerSelect.value;
    try {
        const res = await fetch(`/api/models?provider=${provider}`);
        const data = await res.json();
        modelSelect.innerHTML = "";

        if (data.models && data.models.length > 0) {
            data.models.forEach(m => {
                const opt = document.createElement("option");
                opt.value = m;
                opt.textContent = m;
                modelSelect.appendChild(opt);
            });
            // Try to default to a coder model or first model
            const coderModel = data.models.find(m => m.includes("coder") || m.includes("qwen") || m.includes("llama"));
            if (coderModel) modelSelect.value = coderModel;
        } else {
            const opt = document.createElement("option");
            opt.value = "";
            opt.textContent = "⚠️ 모델 없음 (아래에서 다운로드하세요)";
            modelSelect.appendChild(opt);
            if (customModelInput) {
                customModelInput.placeholder = "모델 다운로드 필요 (예: qwen2.5-coder:1.5b)";
            }
        }
    } catch (e) {
        console.error("Failed to fetch models", e);
    }
}

// PROJECT ACTIONS
async function handleSelectProject() {
    const path = projectPathInput.value.trim();
    if (!path) return;

    loadProjectBtn.disabled = true;
    projectInfoBox.innerHTML = `<p class="placeholder-text"><i class="fa-solid fa-spinner fa-spin"></i> 프로젝트를 스캔 및 색인 중입니다...</p>`;

    try {
        const res = await fetch("/api/project/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_path: path })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "프로젝트를 불러오지 못했습니다.");
        }

        const data = await res.json();
        updateProjectUI(data);
    } catch (e) {
        alert("오류: " + e.message);
        projectInfoBox.innerHTML = `<p class="placeholder-text" style="color:var(--accent-rose)">${e.message}</p>`;
    } finally {
        loadProjectBtn.disabled = false;
    }
}

async function handleReindex() {
    if (!confirm("프로젝트를 다시 스캔하고 장기 기억 장치를 갱신하시겠습니까?")) return;
    reindexBtn.disabled = true;
    projectInfoBox.innerHTML = `<p class="placeholder-text"><i class="fa-solid fa-spinner fa-spin"></i> 재색인 중...</p>`;

    try {
        const res = await fetch("/api/project/reindex", { method: "POST" });
        const data = await res.json();
        updateProjectUI(data);
        alert("재색인이 완료되었습니다!");
    } catch (e) {
        alert("재색인 오류: " + e.message);
    } finally {
        reindexBtn.disabled = false;
    }
}

function updateProjectUI(data) {
    activeProject = data;
    const pPath = data.project_path || data.project_root;
    projectPathInput.value = pPath;
    const pName = pPath.split(/[/\\]/).pop() || "Project";
    activeProjectBadge.textContent = pName;

    const stats = data.stats || {};
    statFiles.textContent = (data.total_files || stats.total_files || 0).toLocaleString();
    statChunks.textContent = (data.total_chunks || stats.total_chunks || 0).toLocaleString();
    const tokens = data.total_tokens || stats.total_tokens || 0;
    statTokens.textContent = tokens > 1000 ? Math.round(tokens / 1000) + "k" : tokens;

    projectInfoBox.innerHTML = `
        <div style="font-weight:600; color:var(--accent-cyan); margin-bottom:4px;">${pName}</div>
        <div style="font-size:0.75rem; color:var(--text-secondary); word-break:break-all;">${pPath}</div>
        <div style="margin-top:6px; font-size:0.75rem; color:var(--accent-green)">
            <i class="fa-solid fa-check"></i> ${statFiles.textContent}개 파일 (~${statTokens.textContent} 토큰) 색인 완료
        </div>
    `;

    reindexBtn.disabled = false;
    viewRepoMapBtn.disabled = false;
    sendBtn.disabled = !promptInput.value.trim();
    loadFileTree();
}

function showRepoMapModal() {
    if (!activeProject || !activeProject.repo_map) {
        alert("아직 생성된 구조도가 없습니다.");
        return;
    }
    repoMapContent.textContent = activeProject.repo_map;
    repoModal.classList.add("active");
}

// CHAT & STREAMING
async function sendMessage() {
    const text = promptInput.value.trim();
    if (!text || isStreaming) return;

    if (!activeProject) {
        alert("먼저 프로젝트 폴더를 입력하고 인덱싱해주세요.");
        return;
    }

    // Append User Message to UI
    appendMessage("user", text);
    promptInput.value = "";
    sendBtn.disabled = true;
    isStreaming = true;
    streamStatus.textContent = "컨텍스트 조립 및 로컬 모델 응답 생성 중...";

    // Prepare Assistant Message Placeholder
    const assistantMsgElem = appendMessage("assistant", "");
    const bubble = assistantMsgElem.querySelector(".message-bubble");
    const contextPill = assistantMsgElem.querySelector(".context-tag-pill");
    
    // Model Selection
    const selectedModel = customModelInput.value.trim() || modelSelect.value;
    const provider = providerSelect.value;
    const contextLimit = parseInt(contextLimitSlider.value);
    const temperature = parseFloat(tempSlider.value);

    let accumulatedContent = "";

    try {
        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                prompt: text,
                history: conversationHistory,
                session_id: sessionId,
                provider: provider,
                model_name: selectedModel,
                custom_max_tokens: contextLimit,
                temperature: temperature
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop(); // keep remainder

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const jsonStr = line.replace("data: ", "").trim();
                if (!jsonStr) continue;

                try {
                    const event = JSON.parse(jsonStr);
                    if (event.type === "context_meta") {
                        // Update Context Inspector in real-time
                        updateContextInspector(event.data);
                        if (contextPill) {
                            const cCount = event.data.retrieved_chunks.length;
                            const tokUsed = event.data.total_estimated_tokens;
                            contextPill.innerHTML = `<i class="fa-solid fa-microchip"></i> 주입된 청크 ${cCount}개 (~${tokUsed} tok)`;
                            contextPill.style.display = "inline-flex";
                        }
                    } else if (event.type === "token") {
                        accumulatedContent += event.token;
                        bubble.innerHTML = marked.parse(accumulatedContent);
                        hljs.highlightAll();
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    } else if (event.type === "tool_call") {
                        const callBanner = document.createElement("div");
                        callBanner.className = "tool-call-banner";
                        callBanner.innerHTML = `<i class="fa-solid fa-gear fa-spin"></i> [도구 실행] <strong>${escapeHtml(event.tool)}</strong> (${escapeHtml(JSON.stringify(event.args))})`;
                        assistantMsgElem.appendChild(callBanner);
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    } else if (event.type === "tool_result") {
                        const resBox = document.createElement("div");
                        resBox.className = "tool-result-box";
                        resBox.innerHTML = `<div><i class="fa-solid fa-check"></i> <strong>[도구 결과: ${escapeHtml(event.tool)}]</strong></div><pre><code>${escapeHtml(JSON.stringify(event.result, null, 2))}</code></pre>`;
                        assistantMsgElem.appendChild(resBox);
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    } else if (event.type === "proposals") {
                        // Render Code Modification Card
                        renderCodeProposals(assistantMsgElem, event.proposals);
                    } else if (event.type === "error") {
                        bubble.innerHTML += `<div style="color:var(--accent-rose); margin-top:8px;">[오류: ${event.error}]</div>`;
                    }
                } catch (err) {
                    console.error("SSE parse error", err);
                }
            }
        }

        // Add to dialogue history
        conversationHistory.push({ role: "user", content: text });
        conversationHistory.push({ role: "assistant", content: accumulatedContent });

    } catch (e) {
        bubble.innerHTML = `<span style="color:var(--accent-rose)">오류 발생: ${e.message}</span>`;
    } finally {
        isStreaming = false;
        streamStatus.textContent = "";
        sendBtn.disabled = !promptInput.value.trim();
        loadEpisodes(); // Refresh timeline in right pane
    }
}

function appendMessage(role, content) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role}`;

    const header = document.createElement("div");
    header.className = "message-header";
    header.innerHTML = role === "user" ? 
        `<span>나</span> <i class="fa-solid fa-user"></i>` : 
        `<i class="fa-solid fa-robot" style="color:var(--accent-cyan)"></i> <span>ContextForge AI</span>`;

    const pill = document.createElement("div");
    pill.className = "context-tag-pill";
    pill.style.display = "none";
    pill.addEventListener("click", () => {
        // Switch to context tab
        document.querySelector('.tab-btn[data-tab="tab-context"]').click();
    });

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.innerHTML = content ? marked.parse(content) : `<span class="stream-cursor">▌</span>`;

    msgDiv.appendChild(header);
    if (role === "assistant") msgDiv.appendChild(pill);
    msgDiv.appendChild(bubble);

    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return msgDiv;
}

function renderCodeProposals(msgElem, proposals) {
    if (!proposals || proposals.length === 0) return;

    proposals.forEach(p => {
        const box = document.createElement("div");
        box.className = "proposal-box";
        box.innerHTML = `
            <div class="proposal-header">
                <span class="proposal-title">
                    <i class="fa-solid fa-file-pen"></i> ${p.file_path} (${p.action === "modify" ? "파일 수정" : "새 파일 생성"})
                </span>
                <button class="proposal-apply-btn">
                    <i class="fa-solid fa-check"></i> 프로젝트에 코드 반영 (Apply)
                </button>
            </div>
            <pre><code class="language-code">${escapeHtml(p.code_content)}</code></pre>
        `;

        const applyBtn = box.querySelector(".proposal-apply-btn");
        applyBtn.addEventListener("click", async () => {
            if (!confirm(`'${p.file_path}' 파일에 변경 사항을 적용하시겠습니까?\n(기존 파일은 자동으로 .bak 백업됩니다)`)) return;
            applyBtn.disabled = true;
            applyBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 적용 중...`;

            try {
                const res = await fetch("/api/code/apply", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(p)
                });
                const resData = await res.json();
                if (resData.success) {
                    applyBtn.innerHTML = `<i class="fa-solid fa-circle-check"></i> 적용 완료!`;
                    applyBtn.style.background = "var(--accent-purple)";
                    alert(`파일이 성공적으로 적용되었습니다!\n백업 파일: ${resData.backup_created || '없음'}`);
                }
            } catch (err) {
                alert("코드 적용 실패: " + err.message);
                applyBtn.disabled = false;
                applyBtn.innerHTML = `<i class="fa-solid fa-xmark"></i> 실패`;
            }
        });

        msgElem.appendChild(box);
    });
}

// CONTEXT INSPECTOR UPDATER
function updateContextInspector(meta) {
    const bd = meta.budget_breakdown || {};
    const maxBudget = meta.max_context_budget || 4096;

    // Percentages for the progress meter
    const pSys = Math.min(30, (bd.system_instructions / maxBudget) * 100);
    const pRepo = Math.min(25, (bd.repo_map / maxBudget) * 100);
    const pCode = Math.min(60, (bd.relevant_code_snippets / maxBudget) * 100);
    const pMem = Math.min(20, (bd.episodic_memories / maxBudget) * 100);
    const pDial = Math.min(30, (bd.dialogue_history / maxBudget) * 100);

    barSystem.style.width = pSys + "%";
    barRepo.style.width = pRepo + "%";
    barCode.style.width = pCode + "%";
    barMemory.style.width = pMem + "%";
    barDialogue.style.width = pDial + "%";

    compressionRate.textContent = meta.compression_ratio + "%";

    // Injected Chunks List
    injectedChunkCount.textContent = meta.retrieved_chunks.length + "개";
    injectedChunksList.innerHTML = "";

    if (meta.retrieved_chunks.length === 0) {
        injectedChunksList.innerHTML = `<p class="placeholder-text">선별 주입된 코드 청크가 없습니다.</p>`;
    } else {
        meta.retrieved_chunks.forEach(c => {
            const card = document.createElement("div");
            card.className = "chunk-card";
            card.innerHTML = `
                <div class="chunk-card-header">
                    <span class="chunk-path">${c.file_path}:${c.lines}</span>
                    <span class="chunk-score">점수: ${c.score}</span>
                </div>
                <div class="chunk-reason">${c.reason}</div>
                <div class="chunk-snippet">${escapeHtml(c.preview)}</div>
            `;
            injectedChunksList.appendChild(card);
        });
    }

    // Injected Memories List
    injectedMemoryCount.textContent = meta.retrieved_memories.length + "개";
    injectedMemoriesList.innerHTML = "";

    if (meta.retrieved_memories.length === 0) {
        injectedMemoriesList.innerHTML = `<p class="placeholder-text">회상된 에피소드 기억이 없습니다.</p>`;
    } else {
        meta.retrieved_memories.forEach(m => {
            const card = document.createElement("div");
            card.className = "memory-card";
            card.innerHTML = `
                <div class="memory-type">${m.type} (점수: ${m.score})</div>
                <div class="memory-summary">${escapeHtml(m.summary)}</div>
            `;
            injectedMemoriesList.appendChild(card);
        });
    }
}

// LTM MANUAL SEARCH
async function handleLtmSearch() {
    const q = ltmSearchInput.value.trim();
    if (!q) return;

    ltmSearchResults.innerHTML = `<p class="placeholder-text"><i class="fa-solid fa-spinner fa-spin"></i> 검색 중...</p>`;

    try {
        const res = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: q, top_k: 6 })
        });
        const data = await res.json();
        ltmSearchResults.innerHTML = "";

        if (data.code_chunks.length === 0 && data.episodic_memories.length === 0) {
            ltmSearchResults.innerHTML = `<p class="placeholder-text">검색 결과가 없습니다.</p>`;
            return;
        }

        data.code_chunks.forEach(c => {
            const card = document.createElement("div");
            card.className = "chunk-card";
            card.innerHTML = `
                <div class="chunk-card-header">
                    <span class="chunk-path">${c.file_path}:${c.lines}</span>
                    <span class="chunk-score">점수: ${c.score}</span>
                </div>
                <div class="chunk-reason">${c.reason}</div>
                <div class="chunk-snippet">${escapeHtml(c.content.slice(0, 200))}...</div>
            `;
            ltmSearchResults.appendChild(card);
        });
    } catch (e) {
        ltmSearchResults.innerHTML = `<p class="placeholder-text" style="color:var(--accent-rose)">검색 실패: ${e.message}</p>`;
    }
}

// EPISODES TIMELINE
async function loadEpisodes() {
    try {
        const res = await fetch(`/api/memory/recent?session_id=${sessionId}&limit=20`);
        const data = await res.json();
        episodesTimelineList.innerHTML = "";

        if (!data.memories || data.memories.length === 0) {
            episodesTimelineList.innerHTML = `<p class="placeholder-text">기록된 에피소드가 없습니다.</p>`;
            return;
        }

        data.memories.forEach(m => {
            const item = document.createElement("div");
            item.className = "memory-card";
            item.innerHTML = `
                <div class="memory-type">${m.type}</div>
                <div class="memory-summary">${escapeHtml(m.summary)}</div>
                <div style="font-size:0.7rem; color:var(--text-muted); margin-top:2px;">${escapeHtml(m.detail.slice(0, 100))}</div>
            `;
            episodesTimelineList.appendChild(item);
        });
    } catch (e) {
        console.warn("Could not load episodes", e);
    }
}

async function handleClearMemory() {
    if (!confirm("현재 세션의 대화 기억을 초기화하시겠습니까?")) return;
    await fetch("/api/memory/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId })
    });
    loadEpisodes();
    alert("세션 기억이 초기화되었습니다.");
}

function escapeHtml(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// --- MCP MANAGEMENT FUNCTIONS ---
async function loadMCPServers() {
    if (!mcpServersList) return;
    try {
        const [serverRes, toolRes] = await Promise.all([
            fetch("/api/mcp/servers"),
            fetch("/api/mcp/tools")
        ]);

        const servers = await serverRes.json();
        const toolsData = await toolRes.json();
        const tools = toolsData.tools || [];

        // Update badge
        if (mcpStatusText) {
            mcpStatusText.textContent = `도구: 기본 4개 + MCP ${tools.length}개`;
        }
        if (mcpToolsCountBadge) {
            mcpToolsCountBadge.textContent = `${tools.length}개`;
        }

        // Render Servers
        mcpServersList.innerHTML = "";
        const serverKeys = Object.keys(servers);
        if (serverKeys.length === 0) {
            mcpServersList.innerHTML = `<p class="placeholder-text">등록된 MCP 서버가 없습니다.</p>`;
        } else {
            serverKeys.forEach(name => {
                const s = servers[name];
                const card = document.createElement("div");
                card.className = "mcp-server-card";
                card.innerHTML = `
                    <div class="mcp-server-info">
                        <span class="mcp-server-name">${escapeHtml(name)}</span>
                        <span class="mcp-server-desc">도구 ${s.tools ? s.tools.length : 0}개 | ${escapeHtml(s.status || '')}</span>
                    </div>
                    <div class="mcp-server-actions">
                        <span class="mcp-status-tag ${s.connected ? 'online' : 'offline'}">
                            ${s.connected ? '연결됨' : '연결 끊김'}
                        </span>
                        <button class="icon-btn-sm" data-delete-mcp="${escapeHtml(name)}" title="삭제">
                            <i class="fa-solid fa-trash" style="color:var(--accent-rose)"></i>
                        </button>
                    </div>
                `;
                const delBtn = card.querySelector(`[data-delete-mcp]`);
                delBtn.addEventListener("click", () => handleDeleteMCPServer(name));
                mcpServersList.appendChild(card);
            });
        }

        // Render Tools
        mcpToolsList.innerHTML = "";
        if (tools.length === 0) {
            mcpToolsList.innerHTML = `<p class="placeholder-text">사용 가능한 MCP 도구가 없습니다.</p>`;
        } else {
            tools.forEach(t => {
                const card = document.createElement("div");
                card.className = "mcp-tool-card";
                card.innerHTML = `
                    <div class="mcp-tool-header">
                        <span class="mcp-tool-name">${escapeHtml(t.server_name)}__${escapeHtml(t.name)}</span>
                        <button class="btn btn-secondary btn-sm" data-run-tool="${escapeHtml(t.server_name)}__${escapeHtml(t.name)}">
                            <i class="fa-solid fa-play"></i> 테스트 실행
                        </button>
                    </div>
                    <div class="mcp-tool-desc">${escapeHtml(t.description || '설명 없음')}</div>
                `;
                const runBtn = card.querySelector(`[data-run-tool]`);
                runBtn.addEventListener("click", () => handleTestTool(`${t.server_name}__${t.name}`));
                mcpToolsList.appendChild(card);
            });
        }

    } catch (e) {
        console.warn("Failed to load MCP status", e);
    }
}

async function handleAddMCPServer() {
    const name = mcpNameInput.value.trim();
    const transport = mcpTransportSelect.value;
    const command = mcpCommandInput.value.trim();
    const rawArgs = mcpArgsInput.value.trim();
    const url = mcpUrlInput.value.trim();

    if (!name) {
        alert("서버 이름을 입력해주세요.");
        return;
    }

    if (transport === "stdio" && !command) {
        alert("실행 명령어(Command)를 입력해주세요 (예: uvx, npx, python).");
        return;
    }

    if (transport === "sse" && !url) {
        alert("SSE URL을 입력해주세요.");
        return;
    }

    const args = rawArgs ? rawArgs.split(",").map(a => a.trim()).filter(Boolean) : [];

    addMcpServerBtn.disabled = true;
    addMcpServerBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 연결 중...`;

    try {
        const res = await fetch("/api/mcp/server", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name,
                transport,
                command: transport === "stdio" ? command : null,
                args: transport === "stdio" ? args : [],
                url: transport === "sse" ? url : null,
                enabled: true
            })
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "연결 실패");
        }

        alert(`MCP 서버 '${name}' 연결 성공!\n${data.message}`);
        mcpNameInput.value = "";
        mcpCommandInput.value = "";
        mcpArgsInput.value = "";
        mcpUrlInput.value = "";
        await loadMCPServers();

    } catch (e) {
        alert("MCP 서버 추가 오류: " + e.message);
    } finally {
        addMcpServerBtn.disabled = false;
        addMcpServerBtn.innerHTML = `<i class="fa-solid fa-link"></i> 서버 등록 및 연결`;
    }
}

async function handleDeleteMCPServer(name) {
    if (!confirm(`'${name}' MCP 서버를 삭제하시겠습니까?`)) return;
    try {
        await fetch(`/api/mcp/server?name=${encodeURIComponent(name)}`, { method: "DELETE" });
        await loadMCPServers();
    } catch (e) {
        alert("삭제 실패: " + e.message);
    }
}

async function handleTestTool(namespacedToolName) {
    const rawArgs = prompt(`도구 '${namespacedToolName}'에 전달할 JSON 인자를 입력하세요:\n(인자가 없으면 {} 입력)`, "{}");
    if (rawArgs === null) return;

    let parsedArgs = {};
    try {
        parsedArgs = JSON.parse(rawArgs);
    } catch (e) {
        alert("유효한 JSON 형식이 아닙니다.");
        return;
    }

    try {
        const res = await fetch("/api/mcp/tool/call", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tool_name: namespacedToolName,
                arguments: parsedArgs
            })
        });
        const result = await res.json();
        alert(`[실행 결과]\n${JSON.stringify(result, null, 2)}`);
    } catch (e) {
        alert("도구 실행 오류: " + e.message);
    }
}

// --- MODEL PULL FUNCTIONS ---
async function handlePullModel() {
    const modelName = pullModelNameInput.value.trim();
    if (!modelName) {
        alert("다운로드할 모델명을 입력하세요 (예: qwen2.5-coder:1.5b)");
        return;
    }

    pullModelBtn.disabled = true;
    pullProgressContainer.style.display = "flex";
    pullProgressBar.style.width = "0%";
    pullStatusText.textContent = `'${modelName}' 모델 다운로드 요청 중...`;

    try {
        const response = await fetch("/api/models/pull", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_name: modelName })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const jsonStr = line.replace("data: ", "").trim();
                if (!jsonStr) continue;

                try {
                    const evt = JSON.parse(jsonStr);
                    if (evt.status) {
                        let percentStr = "";
                        if (evt.total && evt.completed) {
                            const pct = Math.min(100, Math.round((evt.completed / evt.total) * 100));
                            pullProgressBar.style.width = pct + "%";
                            percentStr = ` (${pct}%)`;
                        }
                        pullStatusText.textContent = `${evt.status}${percentStr}`;
                    }
                } catch (e) {
                    console.error("Pull parse error", e);
                }
            }
        }

        pullProgressBar.style.width = "100%";
        pullStatusText.textContent = `✅ '${modelName}' 다운로드 완료!`;
        await fetchModels();
        modelSelect.value = modelName;
        alert(`'${modelName}' 모델이 성공적으로 다운로드되었습니다! 이제 AI와 대화할 수 있습니다.`);
    } catch (e) {
        pullStatusText.textContent = `❌ 오류: ${e.message}`;
        alert(`모델 다운로드 실패: ${e.message}`);
    } finally {
        pullModelBtn.disabled = false;
    }
}

// --- PROJECT FILE EXPLORER & EDITOR FUNCTIONS ---
async function loadFileTree() {
    if (!fileTreeContainer) return;
    fileTreeContainer.innerHTML = `<p class="placeholder-text"><i class="fa-solid fa-spinner fa-spin"></i> 파일 목록 로딩 중...</p>`;

    try {
        const res = await fetch("/api/file/tree");
        const data = await res.json();
        const tree = data.tree || [];

        if (tree.length === 0) {
            fileTreeContainer.innerHTML = `<p class="placeholder-text">표시할 프로젝트 파일이 없습니다.</p>`;
            return;
        }

        fileTreeContainer.innerHTML = "";
        tree.forEach(item => {
            const row = document.createElement("div");
            row.className = `tree-item ${item.is_dir ? 'is-dir' : 'is-file'}`;
            if (currentEditingPath === item.path) row.classList.add("selected");

            const iconClass = item.is_dir ? "fa-folder" : getFileIcon(item.name);
            const sizeStr = item.size ? formatBytes(item.size) : "";

            row.innerHTML = `
                <i class="fa-solid ${iconClass} tree-icon"></i>
                <span class="tree-name" title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</span>
                <span class="tree-size">${sizeStr}</span>
            `;

            if (!item.is_dir) {
                row.addEventListener("click", () => handleOpenFile(item.path, row));
            }
            fileTreeContainer.appendChild(row);
        });
    } catch (e) {
        fileTreeContainer.innerHTML = `<p class="placeholder-text" style="color:var(--accent-rose)">파일 목록 로드 실패: ${e.message}</p>`;
    }
}

function getFileIcon(filename) {
    if (!filename) return "fa-file";
    if (filename.endsWith(".py")) return "fa-brands fa-python";
    if (filename.endsWith(".js") || filename.endsWith(".ts")) return "fa-brands fa-js";
    if (filename.endsWith(".html")) return "fa-brands fa-html5";
    if (filename.endsWith(".css")) return "fa-brands fa-css3-alt";
    if (filename.endsWith(".json")) return "fa-code";
    if (filename.endsWith(".md")) return "fa-file-lines";
    return "fa-file-code";
}

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

async function handleOpenFile(relPath, rowElement) {
    document.querySelectorAll(".tree-item").forEach(r => r.classList.remove("selected"));
    if (rowElement) rowElement.classList.add("selected");

    currentEditingPath = relPath;
    activeFilePath.textContent = relPath;
    fileEditorStatus.textContent = "파일 불러오는 중...";
    fileEditorStatus.style.color = "var(--text-secondary)";
    fileEditorSection.style.display = "flex";

    try {
        const res = await fetch("/api/file/read", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ file_path: relPath })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "읽기 실패");

        fileEditorContent.value = data.content;
        fileEditorStatus.textContent = `불러옴 (${data.total_lines}줄, ${data.total_chars}자)`;
        fileEditorStatus.style.color = "var(--accent-green)";
    } catch (e) {
        fileEditorStatus.textContent = `읽기 오류: ${e.message}`;
        fileEditorStatus.style.color = "var(--accent-rose)";
    }
}

async function handleSaveFile() {
    if (!currentEditingPath) return;
    if (!confirm(`'${currentEditingPath}' 파일을 저장하시겠습니까?\n기존 내용은 타임스탬프 .bak 백업 파일로 자동 보관됩니다.`)) return;

    saveFileBtn.disabled = true;
    fileEditorStatus.textContent = "저장 및 백업 생성 중...";
    fileEditorStatus.style.color = "var(--accent-cyan)";

    try {
        const res = await fetch("/api/file/edit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                file_path: currentEditingPath,
                content: fileEditorContent.value
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "저장 실패");

        fileEditorStatus.textContent = `✅ 저장 완료! (자동 백업: ${data.backup_path})`;
        fileEditorStatus.style.color = "var(--accent-green)";
        loadFileTree();
    } catch (e) {
        fileEditorStatus.textContent = `❌ 저장 실패: ${e.message}`;
        fileEditorStatus.style.color = "var(--accent-rose)";
    } finally {
        saveFileBtn.disabled = false;
    }
}

async function handleCreateNewFile() {
    const relPath = prompt("생성할 새 파일의 상대 경로를 입력하세요:\n(예: src/utils/helper.py, notes.md)");
    if (!relPath || !relPath.trim()) return;

    try {
        const res = await fetch("/api/file/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                file_path: relPath.trim(),
                content: ""
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "생성 실패");

        alert(`'${relPath}' 파일이 생성되었습니다.`);
        await loadFileTree();
        handleOpenFile(relPath.trim());
    } catch (e) {
        alert("파일 생성 오류: " + e.message);
    }
}
