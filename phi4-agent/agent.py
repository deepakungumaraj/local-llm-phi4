import json
import os
import re
import uuid
import asyncio
from typing import TypedDict, Annotated
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from tools import tools as local_tools

MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
llm = ChatOllama(model=MODEL, timeout=120, num_ctx=4096)

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


def _build_tool_descriptions(tool_map):
    """Generate a tool description block for the system prompt."""
    lines = ["\n## Tool Definitions\n",
             "When you need to call a tool, output ONLY a JSON array on a line by itself:",
             '```',
             '[{"name": "tool_name", "arguments": {"arg1": "value1"}}]',
             '```',
             "Do NOT add any text before or after the JSON. Do NOT simulate tool results.\n"]
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
        desc = tool.description.split('\n')[0] if tool.description else ""
        params = []
        for pname, pdef in props.items():
            if pname.startswith("_"):
                continue
            ptype = pdef.get("type", "string")
            pdesc = pdef.get("description", "")
            req = " (required)" if pname in required else " (optional)"
            params.append(f"    - {pname}: {ptype}{req} — {pdesc}")
        lines.append(f"### {name}")
        lines.append(f"{desc}")
        if params:
            lines.append("  Parameters:")
            lines.extend(params)
        lines.append("")
    return "\n".join(lines)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def build_agent(extra_tools=None):
    all_tools = list(local_tools) + (extra_tools or [])
    tool_map = {t.name: t for t in all_tools}
    base_prompt = _load_system_prompt()
    tool_desc = _build_tool_descriptions(tool_map)
    system_prompt = base_prompt + "\n" + tool_desc
    print(f"[Agent] System prompt total: {len(system_prompt)} chars, {len(tool_map)} tools")

    async def agent_node(state: AgentState):
        print("\n[Agent] Thinking...")
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=system_prompt)] + list(msgs)
        response = await llm.ainvoke(msgs)

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

        return {"messages": [response]}

    async def tool_node(state: AgentState):
        last_message = state["messages"][-1]
        tool_results = []
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"\n[Tool] Calling: {tool_name} with args: {tool_args}")
            if tool_name in tool_map:
                try:
                    result = await tool_map[tool_name].ainvoke(tool_args)
                except Exception as e:
                    result = f"Error calling {tool_name}: {e}"
                    print(f"[Tool] Error: {e}")
            else:
                result = f"Tool '{tool_name}' not found."
            tool_results.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )
        return {"messages": tool_results}

    def should_continue(state: AgentState):
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "call_tool"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"call_tool": "tools", END: END},
    )
    graph.add_edge("tools", "agent")
    return graph.compile()
