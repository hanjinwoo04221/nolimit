import re
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel, Field
from src.core.config import config, SystemConfig
from src.core.chunker import CodeChunk, estimate_tokens
from src.core.memory import LongTermMemoryManager, EpisodicMemory

class DialogueTurn(BaseModel):
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: float = 0.0

class AssembledContext(BaseModel):
    system_prompt: str
    messages: List[Dict[str, str]]
    total_estimated_tokens: int
    max_context_budget: int
    budget_breakdown: Dict[str, int]
    retrieved_chunks: List[Dict[str, Any]]
    retrieved_memories: List[Dict[str, Any]]
    project_total_tokens: int
    compression_ratio: float

class DynamicContextAssembler:
    """
    Intelligently budgets and constructs the high-signal context window
    for local LLMs with limited context length.
    """
    def __init__(self, memory_mgr: LongTermMemoryManager, sys_config: Optional[SystemConfig] = None):
        self.memory = memory_mgr
        self.config = sys_config or config

    def assemble(
        self,
        current_prompt: str,
        dialogue_history: List[DialogueTurn],
        session_id: str = "default",
        custom_max_tokens: Optional[int] = None
    ) -> AssembledContext:
        """
        Dynamically extracts relevant project parts + past memories + recent turns,
        ensuring the result strictly fits inside the model's context window.
        """
        max_context = custom_max_tokens or self.config.max_context_tokens
        max_output = self.config.max_output_tokens
        available_input_budget = max(500, max_context - max_output)

        # 1. Budget breakdown (in tokens)
        system_budget = int(available_input_budget * self.config.system_ratio)
        repo_map_budget = int(available_input_budget * self.config.repo_map_ratio)
        code_budget = int(available_input_budget * self.config.code_chunks_ratio)
        memory_budget = int(available_input_budget * self.config.memories_ratio)
        dialogue_budget = int(available_input_budget * self.config.dialogue_ratio)

        # 2. Query formulation & keyword extraction
        search_query = self._expand_query(current_prompt, dialogue_history)

        # 3. Retrieve relevant project chunks from Long-Term Memory
        retrieved_code = self.memory.retrieve_relevant_code(search_query, top_k=self.config.top_k_chunks)
        selected_chunks: List[Tuple[CodeChunk, float, str]] = []
        accumulated_code_tokens = 0

        for chunk, score, reason in retrieved_code:
            c_tok = chunk.token_count + 35  # file header overhead
            if accumulated_code_tokens + c_tok <= code_budget:
                selected_chunks.append((chunk, score, reason))
                accumulated_code_tokens += c_tok
            elif not selected_chunks:
                # Always allow at least 1 top chunk even if slightly over
                selected_chunks.append((chunk, score, reason))
                accumulated_code_tokens += c_tok
                break

        # 4. Retrieve relevant episodic memories from Long-Term Memory
        retrieved_mems = self.memory.retrieve_relevant_memories(search_query, session_id=session_id, top_k=self.config.top_k_memories)
        selected_memories: List[Tuple[EpisodicMemory, float]] = []
        accumulated_mem_tokens = 0

        for mem, score in retrieved_mems:
            m_text = f"- [{mem.memory_type}] {mem.summary}: {mem.detail[:150]}"
            m_tok = estimate_tokens(m_text)
            if accumulated_mem_tokens + m_tok <= memory_budget:
                selected_memories.append((mem, score))
                accumulated_mem_tokens += m_tok

        # 5. Load Repo Map from Memory
        _, full_repo_map = self.memory.load_project_chunks()
        repo_map_snippet = self._trim_repo_map(full_repo_map, repo_map_budget)

        # 6. Format System Persona & Core Instructions
        system_persona = (
            "You are an expert Local AI Project Assistant equipped with Infinite-Context Long-Term Memory.\n"
            "The user's project is indexed in long-term storage. Only the most relevant files and code chunks "
            "for the current request have been retrieved and provided below.\n"
            "Guidelines:\n"
            "1. Answer precisely based on the provided project snippets and architecture.\n"
            "2. When proposing code modifications or new files, specify the exact file path and use clean code blocks.\n"
            "3. If crucial project context seems missing, you can mention which file or symbol you need more details about.\n"
            "4. Respond concisely and professionally in the user's language (Korean/English)."
        )

        # 7. Build Project Context Block
        context_parts = []

        if repo_map_snippet:
            context_parts.append(f"### [PROJECT OVERVIEW & DIRECTORY SKELETON]\n{repo_map_snippet}")

        if selected_memories:
            mem_text_list = [f"- [{m.memory_type.upper()}] {m.summary} ({m.detail})" for m, _ in selected_memories]
            context_parts.append("### [RECALLED EPISODIC MEMORIES & PAST DECISIONS]\n" + "\n".join(mem_text_list))

        if selected_chunks:
            chunk_blocks = []
            for c, score, reason in selected_chunks:
                header = f"// File: {c.file_path} (lines {c.start_line}-{c.end_line}) | Symbol: {c.symbol_name or 'N/A'}"
                chunk_blocks.append(f"```\n{header}\n{c.content}\n```")
            context_parts.append("### [RELEVANT PROJECT CODE SNIPPETS (FROM LONG-TERM MEMORY)]\n" + "\n\n".join(chunk_blocks))
        else:
            context_parts.append("### [RELEVANT PROJECT CODE SNIPPETS]\n(No specific code snippets matched this query directly)")

        injected_context_text = "\n\n".join(context_parts)
        injected_context_tokens = estimate_tokens(injected_context_text)

        # 8. Budget and select recent dialogue history (working memory)
        working_turns: List[Dict[str, str]] = []
        dialogue_tokens_used = 0

        # Iterate dialogue history in reverse (most recent first)
        for turn in reversed(dialogue_history):
            turn_tokens = estimate_tokens(turn.content) + 10
            if dialogue_tokens_used + turn_tokens <= dialogue_budget:
                working_turns.insert(0, {"role": turn.role, "content": turn.content})
                dialogue_tokens_used += turn_tokens
            else:
                break

        # 9. Final messages array for the LLM
        final_system_content = f"{system_persona}\n\n{injected_context_text}"
        messages = [
            {"role": "system", "content": final_system_content}
        ]
        messages.extend(working_turns)
        messages.append({"role": "user", "content": current_prompt})

        # Token counting
        total_estimated = (
            estimate_tokens(final_system_content) + 
            dialogue_tokens_used + 
            estimate_tokens(current_prompt)
        )

        stats = self.memory.get_stats()
        project_total_tok = stats.get("total_tokens", 0)
        compression_ratio = round((1.0 - (accumulated_code_tokens / max(1, project_total_tok))) * 100, 1) if project_total_tok > 0 else 0.0

        # Visual inspector metadata
        retrieved_chunks_meta = [
            {
                "file_path": c.file_path,
                "lines": f"{c.start_line}-{c.end_line}",
                "symbol": c.symbol_name or "N/A",
                "tokens": c.token_count,
                "score": round(score, 4),
                "reason": reason,
                "preview": c.content[:180] + ("..." if len(c.content) > 180 else "")
            }
            for c, score, reason in selected_chunks
        ]

        retrieved_mems_meta = [
            {
                "type": m.memory_type,
                "summary": m.summary,
                "detail": m.detail[:100],
                "score": round(score, 4)
            }
            for m, score in selected_memories
        ]

        breakdown = {
            "system_instructions": estimate_tokens(system_persona),
            "repo_map": estimate_tokens(repo_map_snippet),
            "relevant_code_snippets": accumulated_code_tokens,
            "episodic_memories": accumulated_mem_tokens,
            "dialogue_history": dialogue_tokens_used,
            "user_prompt": estimate_tokens(current_prompt),
            "total_input": total_estimated,
            "available_budget": available_input_budget,
            "max_context_limit": max_context
        }

        return AssembledContext(
            system_prompt=final_system_content,
            messages=messages,
            total_estimated_tokens=total_estimated,
            max_context_budget=max_context,
            budget_breakdown=breakdown,
            retrieved_chunks=retrieved_chunks_meta,
            retrieved_memories=retrieved_mems_meta,
            project_total_tokens=project_total_tok,
            compression_ratio=compression_ratio
        )

    def _expand_query(self, prompt: str, history: List[DialogueTurn]) -> str:
        """Enriches the query with context from recent turns and extracted filenames/symbols."""
        query_parts = [prompt]
        # Include previous user turn if available for coreference resolution
        for turn in reversed(history[-2:]):
            if turn.role == "user":
                query_parts.append(turn.content)
                break
        
        # Extract potential filenames like *.py, *.js, *.html
        file_matches = re.findall(r'[a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+', prompt)
        if file_matches:
            query_parts.extend(file_matches)

        return " ".join(query_parts)

    def _trim_repo_map(self, full_map: str, max_tokens: int) -> str:
        """Trims repo map if it exceeds the allocated budget."""
        if not full_map:
            return ""
        tokens = estimate_tokens(full_map)
        if tokens <= max_tokens:
            return full_map

        lines = full_map.splitlines()
        trimmed_lines = []
        curr_tokens = 0
        for l in lines:
            tok = estimate_tokens(l)
            if curr_tokens + tok > max_tokens - 20:
                trimmed_lines.append("  ... [additional directory items truncated to save context]")
                break
            trimmed_lines.append(l)
            curr_tokens += tok

        return "\n".join(trimmed_lines)
