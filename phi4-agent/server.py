import asyncio
import json
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from agent import build_agent

MCP_SERVERS = {
    "myschedule": {
        "command": "node",
        "args": ["c:/dev/myschedule-mcp/dist/index.js"],
        "transport": "stdio",
    },
}


@asynccontextmanager
async def lifespan(app):
    mcp_tools = []
    client = None
    try:
        client = MultiServerMCPClient(MCP_SERVERS)
        mcp_tools = await asyncio.wait_for(client.get_tools(), timeout=15)
        print(f"[MCP] Loaded {len(mcp_tools)} tools from MCP servers: "
              f"{[t.name for t in mcp_tools]}")
    except asyncio.TimeoutError:
        print("[MCP] WARNING: Timed out connecting to MCP servers — starting without MCP tools")
    except Exception as e:
        print(f"[MCP] WARNING: Failed to load MCP tools ({e}) — starting without MCP tools")
    app.state.agent = build_agent(extra_tools=mcp_tools if mcp_tools else None)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=4096)


@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        result = await app.state.agent.ainvoke(
            {"messages": [HumanMessage(content=request.message)]},
            {"recursion_limit": 25},
        )
        response = result["messages"][-1].content
        return {"response": response}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)},
        )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE endpoint that streams agent progress (thinking, tool calls, final answer)."""
    async def event_generator():
        try:
            yield {"event": "status", "data": json.dumps({"status": "thinking"})}
            async for event in app.state.agent.astream_events(
                {"messages": [HumanMessage(content=request.message)]},
                version="v2",
                config={"recursion_limit": 25},
            ):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield {"event": "token", "data": json.dumps({"token": chunk.content})}
                elif kind == "on_tool_start":
                    name = event.get("name", "unknown")
                    yield {"event": "tool_start", "data": json.dumps({"tool": name})}
                elif kind == "on_tool_end":
                    name = event.get("name", "unknown")
                    yield {"event": "tool_end", "data": json.dumps({"tool": name})}
            yield {"event": "done", "data": json.dumps({"status": "complete"})}
        except Exception as e:
            traceback.print_exc()
            yield {"event": "error", "data": json.dumps({"detail": str(e)})}

    return EventSourceResponse(event_generator())


@app.get("/health")
def health():
    return {"status": "ok"}
