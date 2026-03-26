from typing import TypedDict, Annotated
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from tools import tools as local_tools

llm = ChatOllama(model="phi4-mini")


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def build_agent(extra_tools=None):
    all_tools = list(local_tools) + (extra_tools or [])
    llm_with_tools = llm.bind_tools(all_tools)
    tool_map = {t.name: t for t in all_tools}

    def agent_node(state: AgentState):
        print("\n[Agent] Thinking...")
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    def tool_node(state: AgentState):
        last_message = state["messages"][-1]
        tool_results = []
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"\n[Tool] Calling: {tool_name} with args: {tool_args}")
            if tool_name in tool_map:
                result = tool_map[tool_name].invoke(tool_args)
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
