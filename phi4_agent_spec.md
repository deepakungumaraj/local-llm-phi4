# Local AI Agent — Implementation Specification

**Stack:** Microsoft Phi-4 · Ollama · LangChain · LangGraph · FastAPI · React  
**Platform:** Windows 10 / 11 · Local deployment, no cloud required

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Environment Setup](#3-environment-setup)
4. [Project Structure](#4-project-structure)
5. [Tool Definitions — tools.py](#5-tool-definitions--toolspy)
6. [LangGraph Agent — agent.py](#6-langgraph-agent--agentpy)
7. [FastAPI Backend — server.py](#7-fastapi-backend--serverpy)
8. [Frontend UI](#8-frontend-ui)
9. [Running the System](#9-running-the-system)
10. [LangChain's Role](#10-langchains-role)
11. [Extending the System](#11-extending-the-system)
12. [Known Limitations](#12-known-limitations)
13. [Python Dependencies Reference](#13-python-dependencies-reference)

---

## 1. Overview

This document specifies the complete implementation of a locally-deployed, multi-step AI agent running on Windows. The system uses Microsoft Phi-4 as the language model, served by Ollama, orchestrated by LangGraph, and connected to the user through a React chat interface backed by a FastAPI server.

The agent is capable of reasoning across multiple steps, invoking custom tools (such as a calculator, weather lookup, or knowledge base search), observing tool results, and looping until it arrives at a final answer — all running entirely offline on the user's machine.

---

## 2. Architecture

### 2.1 Layer Overview

| Layer | Components | Responsibility |
|---|---|---|
| UI | React, Streamlit, or Open WebUI | Renders the chat interface and sends user messages to the backend |
| API | FastAPI | Receives HTTP requests from the UI, invokes the LangGraph agent, returns the response |
| Agent loop | LangGraph + LangChain | Stateful graph that calls Phi-4, decides whether to use a tool, runs the tool, and loops until done |
| LLM | Ollama + Phi-4 | Loads the model into memory and serves it as a local REST API on port 11434 |

### 2.2 Request and Response Flow

1. User types a message in the chat UI.
2. The UI sends a `POST /chat` request to FastAPI (port 8000) with the message in the request body.
3. FastAPI calls `agent.invoke()` on the compiled LangGraph agent, passing the message as a `HumanMessage`.
4. The agent node sends the full message history to Phi-4 via `ChatOllama` (Ollama on port 11434).
5. Phi-4 returns an `AIMessage`. If it includes `tool_calls`, the router directs execution to the tool node.
6. The tool node identifies the requested tool by name, invokes it, and appends a `ToolMessage` to the state.
7. Control returns to the agent node. Phi-4 observes the tool result and either calls another tool or produces a final answer.
8. Once no `tool_calls` are present in the last `AIMessage`, the router sends execution to `END`.
9. FastAPI extracts the final message content and returns it to the UI as a JSON response.
10. The UI appends the response to the conversation display.

### 2.3 Technology Stack

| Component | Tool | Role |
|---|---|---|
| LLM Model | Microsoft Phi-4 | 14B parameter language model, runs locally |
| LLM Runtime | Ollama | Loads Phi-4 into memory, exposes local REST API |
| LLM Connector | LangChain | ChatOllama client, message types, tool definitions |
| Agent Workflow | LangGraph | Stateful graph: think → act → observe → loop |
| Backend API | FastAPI | HTTP server bridging UI and LangGraph agent |
| Frontend UI | React / Streamlit | Chat interface the user interacts with |

### 2.4 Port Map

| Service | Port | Notes |
|---|---|---|
| Ollama | `11434` | Ollama's default port — do not change |
| FastAPI | `8000` | Backend API — React frontend calls this |
| React UI | `3000` | Default Create React App dev server port |
| Streamlit | `8501` | Alternative Python UI option |
| Open WebUI | `8080` | Ready-made Claude-style UI option |

---

## 3. Environment Setup

### 3.1 System Requirements

| Requirement | Detail |
|---|---|
| OS | Windows 10/11 (64-bit) |
| Python | 3.10 or newer — add to PATH during install |
| Node.js (React only) | 18 LTS or newer |
| RAM | 16 GB minimum; 32 GB recommended |
| Disk space | At least 15 GB free for the Phi-4 model files |
| GPU (optional) | NVIDIA GPU with CUDA for faster inference; CPU works but is slower |

### 3.2 Install Ollama

1. Download the Windows installer from https://ollama.com/download/windows
2. Run the `.exe` installer and follow the setup wizard.
3. Ollama installs as a background service and starts automatically.
4. Verify the install by opening PowerShell and running:

```powershell
ollama --version
```

### 3.3 Pull and Run Phi-4

Open PowerShell and run the following commands. The pull command downloads approximately 9 GB of model data.

```powershell
ollama pull phi4
ollama run phi4
```

Once running, you will see a `>>>` prompt. You can chat with Phi-4 directly here. Press `Ctrl+D` or type `/bye` to exit.

### 3.4 Install Python Dependencies

Install Python 3.10+ from https://python.org/downloads — check **"Add python.exe to PATH"** during install. Then run:

```powershell
pip install langchain langchain-ollama langchain-community langgraph fastapi uvicorn
```

If the `pip` command is not found, use:

```powershell
py -m pip install langchain langchain-ollama langchain-community langgraph fastapi uvicorn
```

---

## 4. Project Structure

Create a project folder and the following files inside it:

```powershell
mkdir phi4-agent
cd phi4-agent
```

```
phi4-agent/
├── tools.py        # Defines @tool-decorated functions the agent can call
├── agent.py        # Builds the LangGraph StateGraph — nodes, edges, routing logic
├── server.py       # FastAPI app — exposes POST /chat and GET /health
├── main.py         # CLI entry point for testing the agent without a UI
└── phi4-ui/        # React frontend (created separately with create-react-app)
    ├── src/
    │   ├── App.js  # Chat window, message list, input bar
    │   └── App.css # Dark-themed chat UI styles
    └── package.json
```

| File | Purpose |
|---|---|
| `tools.py` | Defines `@tool`-decorated functions the agent can call |
| `agent.py` | Builds the LangGraph `StateGraph` — nodes, edges, routing logic |
| `server.py` | FastAPI app — exposes `POST /chat` and `GET /health` |
| `main.py` | CLI entry point for testing the agent without a UI |
| `src/App.js` | React frontend — chat window, message list, input bar |
| `src/App.css` | Dark-themed chat UI styles |

---

## 5. Tool Definitions — `tools.py`

Tools are Python functions decorated with `@tool` from `langchain_core.tools`. The docstring of each function is critical — Phi-4 reads it to understand what the tool does and when to use it.

### 5.1 Defined Tools

| Tool | Input | Returns |
|---|---|---|
| `calculator` | `expression: str` | Evaluated result of a math expression string |
| `get_weather` | `city: str` | Mock weather string — swap in real API |
| `search_knowledge_base` | `query: str` | Keyword match against a dict — swap in vector DB |

### 5.2 Tool Implementation Pattern

Every tool follows this structure. The docstring must explain the purpose and include an example input format.

```python
from langchain_core.tools import tool

@tool
def my_tool(input_param: str) -> str:
    """
    One-sentence description of what this tool does.
    Use this when the user asks about <topic>.
    Example input: 'example value'
    """
    # implementation here
    return result
```

Export all tools in a list at the bottom of `tools.py` so `agent.py` can import them:

```python
tools = [calculator, get_weather, search_knowledge_base]
```

### 5.3 Full tools.py

```python
from langchain_core.tools import tool

@tool
def calculator(expression: str) -> str:
    """
    Evaluates a mathematical expression and returns the result.
    Use this for any math calculations.
    Example input: '25 * 4 + 10'
    """
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_weather(city: str) -> str:
    """
    Returns the current weather for a given city.
    Use this when the user asks about weather.
    Example input: 'London'
    """
    weather_data = {
        "london": "Cloudy, 15°C",
        "new york": "Sunny, 22°C",
        "tokyo": "Rainy, 18°C",
        "paris": "Partly cloudy, 17°C",
    }
    return weather_data.get(city.lower(), f"Weather data not available for {city}")


@tool
def search_knowledge_base(query: str) -> str:
    """
    Searches a knowledge base for information about a topic.
    Use this when the user asks general knowledge questions.
    Example input: 'What is machine learning?'
    """
    knowledge = {
        "machine learning": "Machine learning is a subset of AI where systems learn from data.",
        "langchain": "LangChain is a framework for building LLM-powered applications.",
        "langgraph": "LangGraph is a library for building stateful, multi-actor LLM workflows.",
    }
    for key, value in knowledge.items():
        if key in query.lower():
            return value
    return "No relevant information found in the knowledge base."


tools = [calculator, get_weather, search_knowledge_base]
```

### 5.4 Adding New Tools

1. Define a new `@tool` function in `tools.py` with a clear docstring.
2. Append the function to the `tools` list.
3. Restart the FastAPI server — no other changes required.

The agent discovers tools automatically via `llm.bind_tools(tools)`.

---

## 6. LangGraph Agent — `agent.py`

### 6.1 Agent State

LangGraph is built around a shared state object that flows through every node. Define it as a `TypedDict`:

```python
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
```

The `add_messages` annotation tells LangGraph to append new messages to the list rather than replacing it, preserving the full conversation history.

### 6.2 LLM Initialisation

Initialise `ChatOllama` and bind all tools to it so Phi-4 knows what tools are available:

```python
from langchain_ollama import ChatOllama
from tools import tools

llm = ChatOllama(model="phi4")
llm_with_tools = llm.bind_tools(tools)
```

### 6.3 Nodes

| Node | Type | Behaviour |
|---|---|---|
| `agent_node` | LangGraph node | Sends messages to Phi-4 via `ChatOllama`. Returns `AIMessage`. |
| `tool_node` | LangGraph node | Looks up tool by name, invokes it, returns `ToolMessage`. |
| `should_continue` | Router function | Checks for `tool_calls` on last message. Routes to tool or `END`. |

**Agent node:**

```python
def agent_node(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}
```

**Tool node:**

```python
def tool_node(state: AgentState):
    last_message = state["messages"][-1]
    tool_map = {tool.name: tool for tool in tools}
    tool_results = []
    for tool_call in last_message.tool_calls:
        result = tool_map[tool_call["name"]].invoke(tool_call["args"])
        tool_results.append(
            ToolMessage(content=str(result), tool_call_id=tool_call["id"])
        )
    return {"messages": tool_results}
```

### 6.4 Router

```python
def should_continue(state: AgentState):
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tool"
    return END
```

### 6.5 Graph Assembly

```python
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node)
graph.set_entry_point("agent")
graph.add_conditional_edges(
    "agent",
    should_continue,
    {"call_tool": "tools", END: END}
)
graph.add_edge("tools", "agent")
agent = graph.compile()
```

### 6.6 Full agent.py

```python
from typing import TypedDict, Annotated
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from tools import tools

llm = ChatOllama(model="phi4")
llm_with_tools = llm.bind_tools(tools)

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

def agent_node(state: AgentState):
    print("\n🤖 Agent thinking...")
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

def tool_node(state: AgentState):
    last_message = state["messages"][-1]
    tool_map = {tool.name: tool for tool in tools}
    tool_results = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        print(f"\n🔧 Calling tool: {tool_name} with args: {tool_args}")
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

def build_agent():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"call_tool": "tools", END: END}
    )
    graph.add_edge("tools", "agent")
    return graph.compile()

agent = build_agent()
```

---

## 7. FastAPI Backend — `server.py`

### 7.1 API Endpoints

| Method | Path | Request body | Response |
|---|---|---|---|
| `POST` | `/chat` | `{"message": "..."}` | `{"response": "..."}` |
| `GET` | `/health` | — | `{"status": "ok"}` |

### 7.2 CORS Configuration

CORS must be enabled so the React frontend (port 3000) can call the FastAPI backend (port 8000):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"]
)
```

When deploying to a domain other than localhost, update `allow_origins` to match the actual frontend URL.

### 7.3 Full server.py

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from agent import agent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
async def chat(request: ChatRequest):
    result = agent.invoke({
        "messages": [HumanMessage(content=request.message)]
    })
    response = result["messages"][-1].content
    return {"response": response}

@app.get("/health")
def health():
    return {"status": "ok"}
```

### 7.4 Starting the Server

```powershell
uvicorn server:app --reload --port 8000
```

The `--reload` flag enables hot-reloading during development. Remove it in production.

---

## 8. Frontend UI

### 8.1 UI Option Comparison

| Option | Tech | Best for | Setup time |
|---|---|---|---|
| Open WebUI | Pre-built | Instant Claude-style UI | 5 minutes |
| Streamlit | Python | Python devs, quick prototyping | 15 minutes |
| React + FastAPI | JS + Python | Custom product, full control | 1–2 hours |

### 8.2 Option A: Open WebUI (Fastest)

```powershell
pip install open-webui
open-webui serve
```

Open http://localhost:8080. Phi-4 appears automatically as a model choice.

> **Note:** This option talks directly to Ollama, bypassing the custom LangGraph agent. Use it for plain chat with Phi-4 without custom tool support.

### 8.3 Option B: Streamlit

```powershell
pip install streamlit
streamlit run app.py
```

**app.py:**

```python
import streamlit as st
from langchain_core.messages import HumanMessage
from agent import agent

st.set_page_config(page_title="Phi-4 Assistant", page_icon="🤖")
st.title("🤖 Phi-4 Local Assistant")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask me anything..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
            response = result["messages"][-1].content
            st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
```

Open http://localhost:8501.

### 8.4 Option C: React + FastAPI

**Step 1 — Create the React app:**

```powershell
npx create-react-app phi4-ui
cd phi4-ui
npm start
```

**Step 2 — Replace `src/App.js`:**

```javascript
import { useState } from "react";
import "./App.css";

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMessage = { role: "user", content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input }),
      });
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.response }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", content: "Error connecting to agent." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <div className="header">🤖 Phi-4 Local Assistant</div>
      <div className="chat-window">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            <span className="label">{msg.role === "user" ? "You" : "Phi-4"}</span>
            <p>{msg.content}</p>
          </div>
        ))}
        {loading && (
          <div className="message assistant">
            <span className="label">Phi-4</span>
            <p>Thinking...</p>
          </div>
        )}
      </div>
      <div className="input-area">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Ask me anything..."
        />
        <button onClick={sendMessage} disabled={loading}>Send</button>
      </div>
    </div>
  );
}

export default App;
```

**Step 3 — Replace `src/App.css`:**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: sans-serif; background: #1a1a2e; color: #eee; }

.app { display: flex; flex-direction: column; height: 100vh; max-width: 800px; margin: 0 auto; }
.header { padding: 20px; font-size: 1.4rem; font-weight: bold; background: #16213e; text-align: center; }
.chat-window { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.message { padding: 12px 16px; border-radius: 12px; max-width: 75%; }
.message.user { background: #0f3460; align-self: flex-end; }
.message.assistant { background: #16213e; align-self: flex-start; border: 1px solid #333; }
.label { font-size: 0.75rem; opacity: 0.6; display: block; margin-bottom: 4px; }
.input-area { display: flex; padding: 16px; gap: 10px; background: #16213e; }
.input-area input { flex: 1; padding: 12px; border-radius: 8px; border: 1px solid #333; background: #1a1a2e; color: #eee; font-size: 1rem; }
.input-area button { padding: 12px 24px; background: #0f3460; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 1rem; }
.input-area button:hover { background: #533483; }
```

Open http://localhost:3000.

---

## 9. Running the System

Start each component in a **separate PowerShell window** in this order:

| # | Window | Command | Ready when |
|---|---|---|---|
| 1 | Ollama | `ollama serve` | No output — running silently |
| 2 | FastAPI | `uvicorn server:app --reload` | `Uvicorn running on port 8000` |
| 3 | React UI | `npm start` | `Compiled successfully`, opens browser |

Once all three are running, open http://localhost:3000 and type a message to test the full stack.

### 9.1 Smoke Tests

- **Ollama health:** open http://localhost:11434 in a browser — should return a plain text response.
- **FastAPI health:** open http://localhost:8000/health — should return `{"status": "ok"}`.
- **Agent tool test:** send `"What is 128 * 35?"` — the agent should call the calculator tool and return `4480`.
- **Multi-tool test:** send `"What is the weather in London and multiply the temperature by 5?"` — the agent should call `get_weather` then `calculator` before responding.

---

## 10. LangChain's Role

LangChain does not appear as a standalone service or process. It is a Python library that acts as the glue layer inside `agent.py` and `tools.py`. Every interaction with Phi-4 and every tool definition goes through LangChain abstractions.

| LangChain import | What it provides |
|---|---|
| `ChatOllama` | HTTP client that wraps Ollama's local API for LangGraph use |
| `HumanMessage` | Typed wrapper for a message sent by the user |
| `AIMessage` | Typed wrapper for a message returned by the model |
| `ToolMessage` | Typed wrapper for a tool result passed back to the model |
| `@tool` | Decorator that turns a plain Python function into a LangChain tool |
| `llm.bind_tools()` | Attaches tool schemas to the LLM so Phi-4 knows what tools exist |
| `ChatPromptTemplate` | Optional: structures prompts with variables and system messages |

LangGraph is built on top of LangChain. The `StateGraph`, node pattern, and conditional edges in LangGraph all depend on LangChain message types and tool abstractions at runtime.

---

## 11. Extending the System

### 11.1 Adding a New Tool

1. Open `tools.py`.
2. Define a new `@tool` function with a clear docstring.
3. Append the function to the `tools` list.
4. Restart the FastAPI server — no other changes required.

### 11.2 Swapping the UI

The FastAPI backend is UI-agnostic. Any client that can send a `POST` request to `/chat` with a JSON body of `{"message": "..."}` will work — mobile apps, browser extensions, CLI scripts, or alternative frameworks.

### 11.3 Replacing Mock Data with Real APIs

- **Weather tool:** replace the mock dictionary with a call to OpenWeatherMap or WeatherAPI.
- **Knowledge base tool:** replace the dict with a vector database query using ChromaDB or FAISS plus LangChain's retrieval chain.
- **Stock prices:** integrate the `yfinance` Python package for real market data.

### 11.4 Adding Memory Across Sessions

LangGraph's state is in-memory by default and resets between `agent.invoke()` calls. To persist conversation history across sessions:

1. Add a LangGraph checkpointer such as `SqliteSaver` or `PostgresSaver`.
2. Pass a `thread_id` in the agent config so each conversation has its own state.
3. The agent will automatically recall prior messages within that thread.

---

## 12. Known Limitations

- **Performance:** Phi-4 is a 14B parameter model. On CPU-only machines, inference will be slow — expect 5–30 seconds per response depending on hardware.
- **Mock tools:** The weather and knowledge base tools return static data. They must be replaced with real API calls before production use.
- **No session persistence:** The React frontend does not persist conversation history across page refreshes. Add a backend session store or local storage to fix this.
- **CORS scope:** CORS is configured for `localhost:3000` only. Update `allow_origins` in `server.py` if deploying to a different host or port.
- **No authentication:** The system has no auth layer. Add API key validation or OAuth before exposing the FastAPI server beyond localhost.

---

## 13. Python Dependencies Reference

| Package | Version (min) | Purpose |
|---|---|---|
| `langchain` | 0.3+ | Core LangChain framework |
| `langchain-ollama` | 0.2+ | `ChatOllama` and `OllamaLLM` connectors |
| `langchain-community` | 0.3+ | Community tools and integrations |
| `langgraph` | 0.2+ | `StateGraph`, node/edge orchestration |
| `fastapi` | 0.110+ | Backend HTTP API server |
| `uvicorn` | 0.29+ | ASGI server for FastAPI |

Install all at once:

```powershell
pip install langchain langchain-ollama langchain-community langgraph fastapi uvicorn
```
