import asyncio
import json
import time
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from agent import build_agent, MODEL

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
    allow_origins=["*"],
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


# ──────────────────────────────────────────────────────────────────────
# OpenAI-compatible API (for Open WebUI)
# ──────────────────────────────────────────────────────────────────────

MODEL_ID = f"{MODEL}-agent"


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def openai_chat(request: Request):
    """OpenAI-compatible chat completions endpoint backed by the LangGraph agent."""
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # Convert OpenAI messages to LangChain format — only pass the last user message
    # (the agent prepends its own system prompt with tool definitions)
    last_user = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user = msg["content"]
            break

    if not last_user:
        return JSONResponse(status_code=400, content={"error": "No user message found"})

    if stream:
        return StreamingResponse(
            _openai_stream(last_user),
            media_type="text/event-stream",
        )

    # Non-streaming
    try:
        result = await app.state.agent.ainvoke(
            {"messages": [HumanMessage(content=last_user)]},
            {"recursion_limit": 25},
        )
        content = result["messages"][-1].content
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


async def _openai_stream(user_message: str):
    """Yield OpenAI-compatible SSE chunks from the LangGraph agent."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    sent_role = False
    try:
        async for event in app.state.agent.astream_events(
            {"messages": [HumanMessage(content=user_message)]},
            version="v2",
            config={"recursion_limit": 25},
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    delta = {"content": chunk.content}
                    if not sent_role:
                        delta["role"] = "assistant"
                        sent_role = True
                    payload = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": MODEL_ID,
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
            elif kind == "on_tool_start":
                # Send a visible status so Open WebUI doesn't time out during tool calls
                name = event.get("name", "unknown")
                if not sent_role:
                    delta = {"role": "assistant", "content": f"\n🔧 Calling {name}...\n"}
                    sent_role = True
                else:
                    delta = {"content": f"\n🔧 Calling {name}...\n"}
                payload = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": MODEL_ID,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                yield f"data: {json.dumps(payload)}\n\n"
        # Final chunk with finish_reason
        final = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        traceback.print_exc()
        error_payload = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": f"\n\nError: {e}"},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(error_payload)}\n\n"
        yield "data: [DONE]\n\n"
