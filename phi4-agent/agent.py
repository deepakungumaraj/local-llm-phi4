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

llm = ChatOllama(model="phi4-mini")

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
    re.compile(r'\[?\{["\']name["\']\s*:\s*["\'](\w+)["\'].*?["\']arguments["\']\s*:\s*(\{.*?\})', re.DOTALL),
]


def _parse_text_tool_calls(content, tool_map):
    """Extract tool calls from raw text content when the model doesn't use structured tool_calls."""
    if not content or not isinstance(content, str):
        return []
    calls = []
    try:
        # Try to parse as JSON array of tool calls
        cleaned = content.strip()
        # Remove common surrounding markup tags
        cleaned = re.sub(r'<\|/?[a-z_]+\|>', '', cleaned).strip()
        if cleaned.startswith('['):
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                for item in parsed:
                    name = item.get("name", "")
                    args = item.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args) if args.strip() else {}
                    if name in tool_map:
                        calls.append({"name": name, "args": args, "id": uuid.uuid4().hex[:8]})
                return calls
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    # Fallback: regex extraction
    for pattern in _TOOL_CALL_PATTERNS:
        for match in pattern.finditer(content):
            name = match.group(1)
            try:
                args = json.loads(match.group(2))
            except json.JSONDecodeError:
                args = {}
            if name in tool_map:
                calls.append({"name": name, "args": args, "id": uuid.uuid4().hex[:8]})
    return calls


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def build_agent(extra_tools=None):
    all_tools = list(local_tools) + (extra_tools or [])
    llm_with_tools = llm.bind_tools(all_tools)
    tool_map = {t.name: t for t in all_tools}
    system_prompt = _load_system_prompt()

    def agent_node(state: AgentState):
        print("\n[Agent] Thinking...")
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=system_prompt)] + list(msgs)
        response = llm_with_tools.invoke(msgs)

        # If the model emitted tool calls as raw text instead of structured tool_calls, parse them
        if not (hasattr(response, "tool_calls") and response.tool_calls):
            text_calls = _parse_text_tool_calls(response.content, tool_map)
            if text_calls:
                print(f"[Agent] Parsed {len(text_calls)} tool call(s) from text output")
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
                result = await tool_map[tool_name].ainvoke(tool_args)
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
