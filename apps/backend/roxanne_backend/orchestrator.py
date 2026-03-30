from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import anyio
from anthropic import Anthropic

from roxanne_backend.models import AppConfig, ChatRequest, LLMConfig, ToolEvent
from roxanne_backend.retrieval import SessionMemoryStore
from roxanne_backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _openai_client(llm: LLMConfig):
    """Create an OpenAI-compatible client (works for OpenAI and Ollama)."""
    from openai import OpenAI

    kwargs: Dict[str, Any] = {}
    if llm.api_key:
        kwargs["api_key"] = llm.api_key.get_secret_value()
    else:
        kwargs["api_key"] = "ollama"  # Ollama doesn't need a real key
    if llm.base_url:
        kwargs["base_url"] = llm.base_url
    elif llm.provider == "ollama":
        kwargs["base_url"] = "http://localhost:11434/v1"
    return OpenAI(**kwargs)


class ChatOrchestrator:
    def __init__(
        self,
        config_loader: Callable[[], AppConfig],
        registry_factory: Callable[[AppConfig], ToolRegistry],
        memory_factory: Callable[[AppConfig], SessionMemoryStore],
    ) -> None:
        self.config_loader = config_loader
        self.registry_factory = registry_factory
        self.memory_factory = memory_factory

    async def stream(self, request: ChatRequest) -> AsyncIterator[bytes]:
        config = self.config_loader()
        if not config.is_complete():
            yield self._encode(ToolEvent(type="error", message="Onboarding is incomplete."))
            return

        llm = config.anthropic
        registry = self.registry_factory(config)
        memory = self.memory_factory(config)
        memories = memory.search(request.message, limit=3)
        system_prompt = self._system_prompt(memories, voice_mode=request.voice_mode)

        if llm.provider == "anthropic":
            try:
                async for chunk in self._stream_anthropic(config, registry, memory, request, system_prompt):
                    yield chunk
            except Exception as exc:
                err_str = str(exc).lower()
                if "401" in err_str or "unauthorized" in err_str or "authentication" in err_str:
                    yield self._encode(ToolEvent(type="error", message="Anthropic authentication failed. Check your API key in settings."))
                else:
                    yield self._encode(ToolEvent(type="error", message=f"LLM error: {exc}"))
        elif llm.provider in ("openai", "ollama"):
            # Auto-start Ollama server if needed
            if llm.provider == "ollama":
                try:
                    from roxanne_backend.ollama_manager import ollama_status, start_ollama_server
                    status = await anyio.to_thread.run_sync(ollama_status)
                    if status["installed"] and not status["running"]:
                        yield self._encode(ToolEvent(type="status", message="Starting Ollama server..."))
                        result = await anyio.to_thread.run_sync(start_ollama_server)
                        if not result["ok"]:
                            yield self._encode(ToolEvent(type="error", message=f"Failed to start Ollama: {result.get('error', '')}"))
                            return
                    elif not status["installed"]:
                        yield self._encode(ToolEvent(type="error", message="[SETUP_REQUIRED:ollama] Ollama is not installed."))
                        return
                except Exception as exc:
                    logger.warning(f"Ollama auto-start check failed: {exc}")
            try:
                async for chunk in self._stream_openai(config, registry, memory, request, system_prompt):
                    yield chunk
            except Exception as exc:
                err_str = str(exc).lower()
                if "connection" in err_str and ("refused" in err_str or "error" in err_str):
                    if llm.provider == "ollama":
                        yield self._encode(ToolEvent(type="error", message="[SETUP_REQUIRED:ollama] Cannot connect to Ollama. The server may not be running."))
                    else:
                        yield self._encode(ToolEvent(type="error", message=f"Cannot connect to {llm.base_url or 'the API endpoint'}. Check the URL in settings."))
                elif "not found" in err_str or "not_found" in err_str or "404" in err_str:
                    # Model not pulled yet
                    model = llm.model or "unknown"
                    if llm.provider == "ollama":
                        yield self._encode(ToolEvent(type="error", message=f"[SETUP_REQUIRED:ollama] Model '{model}' is not installed. It needs to be pulled first."))
                    else:
                        yield self._encode(ToolEvent(type="error", message=f"Model '{model}' was not found by the provider. Check the model name in settings."))
                elif "401" in err_str or "unauthorized" in err_str or "authentication" in err_str:
                    yield self._encode(ToolEvent(type="error", message="Authentication failed. Check your API key in settings."))
                else:
                    yield self._encode(ToolEvent(type="error", message=f"LLM error: {exc}"))
        else:
            yield self._encode(ToolEvent(type="error", message=f"Unknown LLM provider: {llm.provider}"))

    # ─── Anthropic provider (true streaming) ──────────────────────

    async def _stream_anthropic(
        self,
        config: AppConfig,
        registry: ToolRegistry,
        memory: SessionMemoryStore,
        request: ChatRequest,
        system_prompt: str,
    ) -> AsyncIterator[bytes]:
        client = Anthropic(api_key=config.anthropic.api_key.get_secret_value())
        # Build messages with conversation history
        messages: List[Dict[str, Any]] = []
        for turn in request.history:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": request.message})

        for _attempt in range(6):
            # Use blocking stream in a thread, collect events via a queue
            import queue
            event_queue: queue.Queue = queue.Queue()
            done_sentinel = object()

            def run_stream():
                try:
                    with client.messages.stream(
                        model=config.anthropic.model,
                        max_tokens=config.anthropic.max_tokens,
                        system=system_prompt,
                        tools=registry.schemas(),
                        messages=messages,
                    ) as stream:
                        for event in stream:
                            event_queue.put(event)
                        # Put the final message
                        event_queue.put(("_final_message", stream.get_final_message()))
                except Exception as exc:
                    event_queue.put(("_error", exc))
                finally:
                    event_queue.put(done_sentinel)

            import threading
            thread = threading.Thread(target=run_stream, daemon=True)
            thread.start()

            # Process events from the stream
            full_text = ""
            assistant_content: List[Dict[str, Any]] = []
            final_message = None

            while True:
                try:
                    item = event_queue.get(timeout=0.05)
                except queue.Empty:
                    await anyio.sleep(0.02)
                    continue

                if item is done_sentinel:
                    break

                if isinstance(item, tuple) and item[0] == "_error":
                    raise item[1]
                if isinstance(item, tuple) and item[0] == "_final_message":
                    final_message = item[1]
                    continue

                event_type = getattr(item, "type", "")

                # Stream text deltas immediately
                if event_type == "content_block_delta":
                    delta = getattr(item, "delta", None)
                    if delta and getattr(delta, "type", "") == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            full_text += text
                            yield self._encode(ToolEvent(type="assistant_delta", delta=text))

            # Build assistant content from the final message
            if final_message:
                assistant_content = [self._serialize_anthropic_block(block) for block in final_message.content]
            messages.append({"role": "assistant", "content": assistant_content})

            tool_calls = [b for b in assistant_content if b.get("type") == "tool_use"]
            if not tool_calls:
                yield self._encode(ToolEvent(type="assistant_done", payload={"message": full_text.strip()}))
                memory.remember(request.session_id, request.message, full_text.strip())
                return

            # Handle tool calls
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                yield self._encode(ToolEvent(type="status", tool=tool_name, message=self._tool_status_msg(tool_name)))
                result = await registry.execute(tool_name, tool_call["input"])
                yield self._encode(ToolEvent(type="tool_result", tool=tool_name, payload=result))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=True),
                })
            messages.append({"role": "user", "content": tool_results})
            # Reset for next loop iteration (tool result → new response)
            full_text = ""

        yield self._encode(ToolEvent(type="error", message="Orchestration loop reached safety limit."))

    def _serialize_anthropic_block(self, block: Any) -> Dict[str, Any]:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            return {"type": "text", "text": getattr(block, "text", "")}
        if block_type == "tool_use":
            return {
                "type": "tool_use",
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}),
            }
        return {"type": block_type or "unknown"}

    # ─── OpenAI / Ollama provider ───────────────────────────────────

    async def _stream_openai(
        self,
        config: AppConfig,
        registry: ToolRegistry,
        memory: SessionMemoryStore,
        request: ChatRequest,
        system_prompt: str,
    ) -> AsyncIterator[bytes]:
        import queue
        import threading

        llm = config.anthropic
        client = _openai_client(llm)
        tools_schemas = self._registry_to_openai_tools(registry)

        # Build messages with conversation history
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        for turn in request.history:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": request.message})

        for _attempt in range(6):
            kwargs: Dict[str, Any] = {
                "model": llm.model,
                "max_tokens": llm.max_tokens,
                "messages": messages,
                "stream": True,
            }
            if tools_schemas:
                kwargs["tools"] = tools_schemas

            # Run streaming in a thread, push chunks via queue
            chunk_queue: queue.Queue = queue.Queue()
            done_sentinel = object()

            def run_stream():
                try:
                    stream = client.chat.completions.create(**kwargs)
                    for chunk in stream:
                        chunk_queue.put(chunk)
                except Exception as exc:
                    chunk_queue.put(("_error", exc))
                finally:
                    chunk_queue.put(done_sentinel)

            thread = threading.Thread(target=run_stream, daemon=True)
            thread.start()

            # Accumulate the streamed response
            full_text = ""
            tool_calls_map: Dict[int, Dict[str, Any]] = {}  # index → {id, name, arguments}

            while True:
                try:
                    item = chunk_queue.get(timeout=0.05)
                except queue.Empty:
                    await anyio.sleep(0.02)
                    continue

                if item is done_sentinel:
                    break
                if isinstance(item, tuple) and item[0] == "_error":
                    raise item[1]

                choice = item.choices[0] if item.choices else None
                if not choice:
                    continue
                delta = choice.delta

                # Stream text content immediately
                if delta and delta.content:
                    full_text += delta.content
                    yield self._encode(ToolEvent(type="assistant_delta", delta=delta.content))

                # Accumulate tool calls (they come in chunks)
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc_delta.id:
                            tool_calls_map[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_map[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_map[idx]["arguments"] += tc_delta.function.arguments

            # Build assistant message for conversation history
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": full_text}
            tool_calls_list = sorted(tool_calls_map.items())

            if tool_calls_list:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for _, tc in tool_calls_list
                ]

            messages.append(assistant_msg)

            if not tool_calls_list:
                yield self._encode(ToolEvent(type="assistant_done", payload={"message": full_text.strip()}))
                memory.remember(request.session_id, request.message, full_text.strip())
                return

            # Execute tool calls
            for _, tc in tool_calls_list:
                tool_name = tc["name"]
                yield self._encode(ToolEvent(type="status", tool=tool_name, message=self._tool_status_msg(tool_name)))
                try:
                    args = json.loads(tc["arguments"])
                except json.JSONDecodeError:
                    args = {}
                result = await registry.execute(tool_name, args)
                yield self._encode(ToolEvent(type="tool_result", tool=tool_name, payload=result))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=True),
                })

        yield self._encode(ToolEvent(type="error", message="Orchestration loop reached safety limit."))

    def _registry_to_openai_tools(self, registry: ToolRegistry) -> List[Dict[str, Any]]:
        """Convert Anthropic-style tool schemas to OpenAI function calling format."""
        anthropic_schemas = registry.schemas()
        openai_tools = []
        for schema in anthropic_schemas:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema.get("description", ""),
                    "parameters": schema.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return openai_tools

    # ─── shared helpers ─────────────────────────────────────────────

    _TOOL_STATUS: Dict[str, str] = {
        "search_zotero": "Searching papers…",
        "search_zotero_metadata": "Looking up metadata…",
        "retrieve_paper_chunks": "Reading paper…",
        "get_paper_metadata": "Getting paper details…",
        "get_paper_notes": "Checking notes…",
        "get_paper_annotations": "Checking highlights…",
        "search_zotero_notes": "Searching notes…",
        "list_zotero_collections": "Listing collections…",
        "get_collection_papers": "Getting collection…",
        "read_notes": "Reading notes…",
        "write_note": "Writing note…",
        "open_pdf": "Opening PDF…",
    }

    def _tool_status_msg(self, tool_name: str) -> str:
        return self._TOOL_STATUS.get(tool_name, f"{tool_name}…")

    def _system_prompt(self, memories: List[Dict[str, Any]], voice_mode: bool = False) -> str:
        memory_block = ""
        if memories:
            snippets = [item["document"] for item in memories]
            memory_block = "\n\nRelevant past session summaries:\n- " + "\n- ".join(snippets)

        if voice_mode:
            citation_rules = (
                "\n\nCitation rules for voice conversation:\n"
                "- If you used a paper, mention it naturally in prose, usually as lead author plus year.\n"
                "- Also include [CITE:file_path_value|page_number_value|short quote] tags for the UI reference chips.\n"
                "- [CITE:...] is the ONLY structured markup allowed in voice conversation mode.\n"
                "- Put [CITE:...] right after the sentence it supports. Do not put it on its own line.\n"
                "- Replace file_path_value with the ACTUAL file_path string from the tool result.\n"
                "- Replace page_number_value with the ACTUAL page_start number from the tool result.\n"
                "- short quote: a brief excerpt (under 40 words) from the chunk you're citing.\n"
                "- Never invent citations. Only cite what tools actually returned.\n"
                "- Never dump full author lists, journal names, or bibliography details unless the user explicitly asks.\n"
            )
        else:
            citation_rules = (
                "\n\nCitation rules (IMPORTANT):\n"
                "- When you use content from a paper, cite it with the author and year inline.\n"
                "- Add a clickable reference using this exact format:\n"
                "  [CITE:file_path_value|page_number_value|short quote]\n"
                "- IMPORTANT: Replace file_path_value with the ACTUAL file_path string from the tool result.\n"
                "  Replace page_number_value with the ACTUAL page_start number from the tool result.\n"
                "  Do NOT write the literal words 'file_path' or 'page_start' — use their values.\n"
                "- Example: If tool returns file_path='/Users/x/paper.pdf' and page_start=12, write:\n"
                "  [CITE:/Users/x/paper.pdf|12|the relevant quote from the text]\n"
                "- short quote: a brief excerpt (under 40 words) from the chunk you're citing.\n"
                "- You can place multiple [CITE:...] references in one response.\n"
                "- Never invent citations. Only cite what tools actually returned.\n"
                "- When equations or math appear, use LaTeX: inline $...$ or display $$...$$\n"
            )

        voice_instructions = ""
        if voice_mode:
            voice_instructions = (
                "\n\nVOICE CONVERSATION MODE:\n"
                "You are in a live voice conversation. Every word you write gets spoken aloud.\n\n"
                "RULES — no exceptions:\n"
                "- MAX 2-3 sentences per response. If more is needed, summarise then ask 'Want details?'\n"
                "- Speak in natural prose only.\n"
                "- NO markdown, NO bullet points, NO numbered lists, NO headings, NO section labels, NO formatting of any kind.\n"
                "- Return plain text only. The only allowed markup is [CITE:...] citation tags for paper references.\n"
                "- Never output literal markdown markers like #, *, -, backticks, tables, or link syntax.\n"
                "- Sound human and conversational, like a smart person talking naturally.\n"
                "- Lead with the answer the user actually wants, not background setup.\n"
                "- Keep the focus on the main point. Do not list long author rosters, journals, tags, or metadata unless the user explicitly asks.\n"
                "- If you are about to make a list, rewrite it as a short spoken explanation instead.\n"
                "- Default to one short paragraph. Only split into two short paragraphs if it really improves clarity.\n"
                "- Contractions are good. Short punchy sentences are good.\n"
                "- Cite conversationally in the sentence itself, like 'Smith 2023 found that…', and also attach the matching [CITE:...] tag.\n\n"
                "TOOL NARRATION (critical):\n"
                "- Before EVERY tool call, say exactly ONE phrase (3-6 words).\n"
                "  Examples: 'Searching now.' / 'Let me check.' / 'Pulling that up.' / 'One sec.'\n"
                "- After results come back, jump straight to the answer. No preamble.\n"
                "  Good: 'Found it. Smith 2023 shows that…'\n"
                "  Bad: 'I have completed my search and found several relevant results…'\n"
            )

        typing_instructions = ""
        if not voice_mode:
            typing_instructions = (
                "\n\nTYPING MODE — normal chat with useful detail:\n"
                "- Answer like a strong normal chatbot: direct first, then useful supporting detail.\n"
                "- By default, give moderate detail, not an exhaustive wall of text.\n"
                "- If the user explicitly asks for lots of detail, a deep dive, or a full breakdown, then expand substantially.\n"
                "- Do not dump long author lists, tags, DOIs, or other bibliographic metadata unless it helps answer the question or the user asks for it.\n"
                "- Give thorough, well-structured answers with markdown formatting when helpful.\n"
                "- Use headings, bullet points, tables, and code blocks where helpful.\n"
                "- For math/equations, ALWAYS use LaTeX: inline $x^2$ or display blocks $$\\sum_{i=1}^n x_i$$\n"
                "- When reproducing equations from papers, convert them to proper LaTeX notation.\n"
                "- Include citations using the [CITE:...] format.\n"
                "- Explain your reasoning and show evidence from papers.\n"
                "- Long, detailed answers are good when the user wants depth.\n"
            )

        return (
            "You are Roxanne, a local-first personal research copilot.\n"
            "Use the provided tools when you need evidence from Zotero or Obsidian.\n"
            "Only write notes when the user explicitly asks you to do so.\n\n"
            "Tool guidance:\n"
            "- search_zotero: semantic search across PDF content (use for topic/concept queries)\n"
            "- search_zotero_metadata: structured search by author, title, tag (use when user names a specific author or paper)\n"
            "- retrieve_paper_chunks: drill into a specific paper's content (equations, methods, formulas)\n"
            "- get_paper_metadata: get full bibliographic info (authors, year, DOI, abstract, tags, collections)\n"
            "- get_paper_notes: get user's notes attached to a paper in Zotero\n"
            "- get_paper_annotations: get PDF highlights and margin comments\n"
            "- search_zotero_notes: semantic search across all Zotero notes and annotations\n"
            "- list_zotero_collections: list all Zotero folders\n"
            "- get_collection_papers: list papers in a specific collection\n"
            "- read_notes / write_note: search and write Obsidian vault notes\n"
            "- open_pdf: resolve a paper to its local file path\n"
            f"{citation_rules}"
            f"{typing_instructions}"
            f"{voice_instructions}"
            f"{memory_block}"
        )


    def _encode(self, event: ToolEvent) -> bytes:
        return (event.model_dump_json() + "\n").encode("utf-8")
