import json
import os
import re
import uuid
import asyncio
import httpx
from typing import TypedDict, Annotated
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from tools import tools as local_tools

MODEL = os.environ.get("OLLAMA_MODEL", "phi4-mini-reasoning:latest")
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# phi4-mini-reasoning: specialized for multi-step reasoning and structured tool calls
# ~2.4GB + 4096 KV cache. Better at instruction following and tool-call sequencing than base phi4-mini.
llm = ChatOllama(model=MODEL, timeout=180, num_ctx=4096, num_gpu=0)

_MAX_RETRIES = 2


async def _reset_ollama_runner():
    """Unload and reload the model to recover from a Vulkan runner crash."""
    print(f"[Ollama] Runner crashed — unloading {MODEL}...")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": MODEL, "keep_alive": 0},
            )
        except Exception:
            pass
    await asyncio.sleep(3)
    print(f"[Ollama] Reloading {MODEL} (warm-up request)...")
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            await client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": MODEL, "prompt": "hi", "stream": False},
            )
        except Exception as e:
            print(f"[Ollama] Warm-up failed: {e}")
    print(f"[Ollama] Runner recovered.")


_INSTRUCTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instructions.md")


def _load_system_prompt():
    """Load system prompt from instructions.md. Falls back to a default if the file is missing."""
    try:
        with open(_INSTRUCTIONS_PATH, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        if prompt:
            print(f"[Agent] Loaded system prompt from {_INSTRUCTIONS_PATH} ({len(prompt)} chars)")
            return prompt
    except FileNotFoundError:
        pass
    return (
        "You are a helpful AI assistant with access to tools. "
        "Call tools when needed. Do not fabricate tool responses."
    )

# Patterns for tool calls that phi4-mini emits as raw text
_TOOL_CALL_PATTERNS = [
    # Standard JSON format: {"name": "...", "arguments": {...}}
    re.compile(r'\{["\']name["\']\s*:\s*["\'](\w+)["\'].*?["\']arguments["\']\s*:\s*(\{.*?\})', re.DOTALL),
    # Function-call style: tool_name(arg1="val1", ...)
    re.compile(r'\b(search_roles|get_roles|view_role|apply_role|seed_token|seed_refresh_token|set_match_id|calculator|get_weather|search_knowledge_base)\s*\(([^)]*)\)', re.DOTALL),
]


def _fix_json(text):
    """Attempt to fix common JSON errors from LLM output."""
    # Fix missing quote before colon in keys: {"key: "value"} → {"key": "value"}
    text = re.sub(r'(\w)(:\s*")', r'\1"\2', text)
    # Fix single quotes used as JSON delimiters
    text = text.replace("'", '"')
    return text


def _parse_text_tool_calls(content, tool_map):
    """Extract tool calls from raw text content when the model doesn't use structured tool_calls."""
    if not content or not isinstance(content, str):
        return []
    calls = []
    # Remove common surrounding markup tags
    cleaned = content.strip()
    cleaned = re.sub(r'<\|/?[a-z_]+\|>', '', cleaned).strip()
    # Remove markdown code fences
    cleaned = re.sub(r'```(?:json)?\s*', '', cleaned).strip()
    # Fix common LLM JSON errors
    cleaned = _fix_json(cleaned)

    # Strategy 1: Try to parse as JSON array of tool calls
    try:
        # Look for JSON array anywhere in the text
        array_match = re.search(r'\[(\s*\{.*?\}\s*(?:,\s*\{.*?\}\s*)*)\]', cleaned, re.DOTALL)
        if array_match:
            parsed = json.loads('[' + array_match.group(1) + ']')
            if isinstance(parsed, list):
                for item in parsed:
                    name = item.get("name", "")
                    args = item.get("arguments", item.get("args", item.get("parameters", {})))
                    if isinstance(args, str):
                        args = json.loads(args) if args.strip() else {}
                    if name in tool_map:
                        calls.append({"name": name, "args": args, "id": uuid.uuid4().hex[:8]})
                if calls:
                    return calls
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    # Strategy 2: Try single JSON object
    try:
        obj_match = re.search(r'\{["\']name["\']\s*:.*?\}(?:\s*\})?', cleaned, re.DOTALL)
        if obj_match:
            parsed = json.loads(obj_match.group(0))
            name = parsed.get("name", "")
            args = parsed.get("arguments", parsed.get("args", parsed.get("parameters", {})))
            if isinstance(args, str):
                args = json.loads(args) if args.strip() else {}
            if name in tool_map:
                calls.append({"name": name, "args": args, "id": uuid.uuid4().hex[:8]})
                return calls
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    # Strategy 3: Regex fallback for JSON-like and function-call patterns
    for pattern in _TOOL_CALL_PATTERNS:
        for match in pattern.finditer(content):
            name = match.group(1)
            if name not in tool_map:
                continue
            raw_args = match.group(2).strip() if match.group(2) else ""
            try:
                if raw_args.startswith('{'):
                    args = json.loads(raw_args)
                elif '=' in raw_args:
                    # Parse function-call style: key="value", key2="value2"
                    args = {}
                    for kv in re.finditer(r'(\w+)\s*=\s*["\']([^"\']*)["\']', raw_args):
                        args[kv.group(1)] = kv.group(2)
                else:
                    args = {}
            except json.JSONDecodeError:
                args = {}
            calls.append({"name": name, "args": args, "id": uuid.uuid4().hex[:8]})
    return calls


def _format_roles_as_table(raw: str) -> str:
    """Parse search_roles / get_roles JSON and return a clean markdown table.
    Falls back to truncated raw text if parsing fails."""
    try:
        data = json.loads(raw)
        # API may return list directly or wrapped in {roles: [...]} or {results: [...]}
        if isinstance(data, dict):
            data = data.get("roles") or data.get("results") or data.get("data") or []
        if not isinstance(data, list) or not data:
            return raw[:1000]

        header = "| Role ID | Title | Client | Location | Start | End | Status |"
        sep    = "|---------|-------|--------|----------|-------|-----|--------|"
        rows = []
        for r in data:
            rid      = r.get("id", "")
            title    = r.get("title", "")[:35]
            client   = r.get("client", "")[:25]
            location = r.get("location", "")
            loc_type = r.get("locationType", "")
            loc_str  = f"{location} ({loc_type})" if loc_type else location
            start    = str(r.get("startDate", ""))[:10]
            end      = str(r.get("endDate", ""))[:10]
            status   = r.get("demandStatus", "")
            rows.append(f"| {rid} | {title} | {client} | {loc_str} | {start} | {end} | {status} |")

        return "\n".join([header, sep] + rows)
    except Exception:
        return raw[:1000]


def _build_tool_descriptions(tool_map):
    """Generate a compact tool description block for the system prompt."""
    lines = [
        "\n## Tools",
        'To call a tool, output ONLY this JSON array and nothing else:',
        '[{"name": "tool_name", "arguments": {"arg1": "val"}}]',
        "IMPORTANT: Never fabricate or simulate tool results. Stop after the JSON — the system will execute the tool and return the real result.\n",
    ]
    for name, tool in tool_map.items():
        try:
            if hasattr(tool, "args_schema") and tool.args_schema:
                schema_obj = tool.args_schema
                if hasattr(schema_obj, "schema"):
                    schema = schema_obj.schema()
                elif isinstance(schema_obj, dict):
                    schema = schema_obj
                else:
                    schema = {}
            else:
                schema = {}
        except Exception:
            schema = {}
        props = schema.get("properties", {})
        required = schema.get("required", [])
        desc = tool.description.split('\n')[0][:120] if tool.description else ""
        params = []
        for pname, pdef in props.items():
            if pname.startswith("_"):
                continue
            ptype = pdef.get("type", "string")
            req = "*" if pname in required else ""
            params.append(f"{pname}{req}:{ptype}")
        param_str = f" ({', '.join(params)})" if params else ""
        lines.append(f"- **{name}**{param_str}: {desc}")
        # Add special note for search_roles about pageSize
        if name == "search_roles":
            lines.append("  ⚠️  **ALWAYS pass `pageSize: 10` to get multiple results**, otherwise only 1 result is returned.")
    return "\n".join(lines)


_MAX_TOOL_ITERATIONS = 8


def _clean_tool_args(name, args):
    """Sanitize tool arguments: remove empty strings, coerce types, fix common LLM mistakes."""
    if not isinstance(args, dict):
        return args
    # Remove keys with empty-string values (LLM often sends level: "", startDate: "")
    cleaned = {k: v for k, v in args.items() if v != ""}
    # For search_roles: "location" should not duplicate "country"
    if name == "search_roles":
        loc = cleaned.get("location", "")
        country = cleaned.get("country", "")
        if loc and loc.upper() == country.upper():
            del cleaned["location"]  # USA is a country, not a metro city
        # Coerce page/pageSize to int
        for k in ("page", "pageSize"):
            if k in cleaned:
                try:
                    cleaned[k] = int(cleaned[k])
                except (ValueError, TypeError):
                    del cleaned[k]
    return cleaned


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int  # counts tool-call rounds; reset per conversation turn



# Keep system prompt + last N messages to avoid context overflow.
# Tool results (search_roles etc.) can be thousands of tokens — truncate aggressively.
_MAX_HISTORY_MESSAGES = 10


def _truncate_history(msgs, max_msgs=_MAX_HISTORY_MESSAGES):
    """Keep the last max_msgs non-system messages.
    Recent tool results (last 2) get 4000 chars — enough for ~10 roles.
    Older tool results get 300 chars to save context space.
    """
    non_system = [m for m in msgs if not isinstance(m, SystemMessage)]
    trimmed = non_system[-max_msgs:]

    # Find indices of ToolMessages so we can apply tiered truncation
    tool_indices = [i for i, m in enumerate(trimmed) if isinstance(m, ToolMessage)]
    recent_tool_indices = set(tool_indices[-2:])  # last 2 tool results stay full-ish

    result = []
    for i, m in enumerate(trimmed):
        if isinstance(m, ToolMessage):
            limit = 4000 if i in recent_tool_indices else 300
            if len(m.content) > limit:
                result.append(ToolMessage(
                    content=m.content[:limit] + "...[truncated]",
                    tool_call_id=m.tool_call_id,
                ))
            else:
                result.append(m)
        else:
            result.append(m)
    return result



def build_agent(extra_tools=None):
    all_tools = list(local_tools) + (extra_tools or [])
    tool_map = {t.name: t for t in all_tools}
    base_prompt = _load_system_prompt()
    tool_desc = _build_tool_descriptions(tool_map)
    system_prompt = base_prompt + "\n" + tool_desc
    print(f"[Agent] System prompt total: {len(system_prompt)} chars, {len(tool_map)} tools")

    async def agent_node(state: AgentState):
        iteration = state.get("iteration", 0)
        print(f"\n[Agent] Thinking... (iteration {iteration})")
        msgs = _truncate_history(state["messages"])
        msgs = [SystemMessage(content=system_prompt)] + msgs
        print(f"[Agent] Sending {len(msgs)} messages to LLM")

        # Retry loop: auto-recover from Vulkan runner crashes
        response = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await llm.ainvoke(msgs)
                break
            except Exception as e:
                err_msg = str(e).lower()
                is_runner_crash = (
                    "unexpectedly stopped" in err_msg
                    or "status code: 500" in err_msg
                    or "connection refused" in err_msg
                    or "connectex" in err_msg
                )
                if is_runner_crash and attempt < _MAX_RETRIES:
                    print(f"[Agent] Vulkan runner crash detected (attempt {attempt + 1}), recovering...")
                    await _reset_ollama_runner()
                    continue
                raise

        # Debug: log what the model actually returned
        print(f"[Agent] Response content_len={len(response.content) if response.content else 0}")
        if response.content:
            preview = response.content[:300].replace('\n', ' ')
            print(f"[Agent] Content preview: {preview}")

        # Parse tool calls from the text output
        text_calls = _parse_text_tool_calls(response.content, tool_map)
        if text_calls:
            print(f"[Agent] Parsed {len(text_calls)} tool call(s): "
                  f"{[c['name'] for c in text_calls]}")
            response = AIMessage(
                content="",
                tool_calls=text_calls,
            )

        return {"messages": [response], "iteration": iteration + 1}

    async def reporter_node(state: AgentState):
        """Runs after all tool calls finish. Synthesizes tool results into a formatted answer."""
        msgs = state["messages"]
        tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]

        # No tools were used — agent's response is already the final answer
        if not tool_msgs:
            return {}

        # Check if agent already gave a proper text answer (not raw JSON)
        last_ai = next(
            (m for m in reversed(msgs) if isinstance(m, AIMessage) and m.content.strip()),
            None,
        )
        def _is_good_answer(text):
            t = text.strip()
            # Raw JSON or truncated tool result echoed back — must synthesize
            if t.startswith('[{') or t.startswith('{"') or t.endswith('...[truncated]]}'):
                return False
            return len(t) > 80

        if last_ai and _is_good_answer(last_ai.content):
            return {}

        # Build synthesis prompt — instruct model to format as markdown table
        tool_summary = "\n\n".join(
            f"Result: {m.content[:2000]}" for m in tool_msgs[-4:]
        )
        synthesis_msgs = [
            SystemMessage(content=(
                "You are a helpful assistant. The tool results below are already formatted "
                "as a markdown table. Present them to the user with a brief 1-sentence intro. "
                "Do NOT reformat, summarise, or omit any rows. Output the table exactly as given."
            )),
            *[m for m in msgs if isinstance(m, HumanMessage)][-2:],
            HumanMessage(content=f"Tool results:\n{tool_summary}\n\nPresent these results:"),
        ]
        try:
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    response = await llm.ainvoke(synthesis_msgs)
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    if attempt < _MAX_RETRIES and (
                        "unexpectedly stopped" in err_msg or "status code: 500" in err_msg
                    ):
                        await _reset_ollama_runner()
                        continue
                    raise
            print(f"[Reporter] Synthesized final answer ({len(response.content)} chars)")
            return {"messages": [AIMessage(content=response.content)]}
        except Exception as e:
            print(f"[Reporter] Error: {e}")
            return {}

    async def tool_node(state: AgentState):
        last_message = state["messages"][-1]
        tool_results = []
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = _clean_tool_args(tool_name, tool_call["args"])
            print(f"\n[Tool] Calling: {tool_name} with args: {tool_args}")
            if tool_name in tool_map:
                try:
                    result = await tool_map[tool_name].ainvoke(tool_args)
                except Exception as e:
                    result = f"Error calling {tool_name}: {e}"
                    print(f"[Tool] Error: {e}")
            else:
                result = f"Tool '{tool_name}' not found."

            # Format role lists as markdown tables so the LLM never sees raw JSON
            result_str = str(result)
            if tool_name in ("search_roles", "get_roles"):
                result_str = _format_roles_as_table(result_str)
                print(f"[Tool] Formatted {tool_name} → {len(result_str)} chars, "
                      f"{result_str.count(chr(10))} rows")

            tool_results.append(
                ToolMessage(content=result_str, tool_call_id=tool_call["id"])
            )
        return {"messages": tool_results}

    def should_continue(state: AgentState):
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            tool_rounds = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
            if tool_rounds >= _MAX_TOOL_ITERATIONS:
                print(f"[Agent] Hit max tool iterations ({_MAX_TOOL_ITERATIONS}), going to reporter.")
                return "report"
            return "call_tool"
        return "report"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("reporter", reporter_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"call_tool": "tools", "report": "reporter"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("reporter", END)
    return graph.compile(checkpointer=MemorySaver())
