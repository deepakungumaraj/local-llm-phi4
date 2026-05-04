import asyncio
import json
import os
import time
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from agent import build_agent, MODEL


def _openai_messages_to_langchain(messages: list) -> list:
    """Convert OpenAI-format messages to LangChain message objects."""
    result = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
    return result

MCP_SERVERS = {
    "myschedule": {
        "command": "node",
        "args": ["c:/dev/myschedule-mcp/dist/index.js"],
        "transport": "stdio",
    },
}

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
REFRESH_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refresh_token.txt")
MATCH_ID = "1941983"


async def _auto_seed_auth(mcp_tools):
    """Seed auth from refresh_token.txt (preferred, ~90 days) or token.txt (~1 hour)."""
    tool_map = {t.name: t for t in mcp_tools}

    # Prefer refresh token — lasts ~90 days
    refresh_token = _read_file(REFRESH_TOKEN_FILE)
    if refresh_token:
        seed_tool = tool_map.get("seed_refresh_token")
        if seed_tool:
            try:
                result = await seed_tool.ainvoke({"refreshToken": refresh_token})
                print(f"[Auth] seed_refresh_token -> {str(result)[:200]}")
                await _set_match_id(tool_map)
                return
            except Exception as e:
                print(f"[Auth] seed_refresh_token failed: {e} — falling back to access token")

    # Fall back to short-lived access token (~1 hour)
    access_token = _read_file(TOKEN_FILE)
    if not access_token:
        print("[Auth] No token found — create token.txt or refresh_token.txt in phi4-agent/")
        return
    seed_tool = tool_map.get("seed_token")
    if seed_tool:
        try:
            result = await seed_tool.ainvoke({"token": access_token})
            print(f"[Auth] seed_token -> {str(result)[:200]}")
        except Exception as e:
            print(f"[Auth] seed_token failed: {e}")
            return
    await _set_match_id(tool_map)


def _read_file(path: str) -> str:
    try:
        content = open(path, "r", encoding="utf-8").read().strip()
        return content if content else ""
    except FileNotFoundError:
        return ""


async def _set_match_id(tool_map: dict):
    match_tool = tool_map.get("set_match_id")
    if match_tool:
        try:
            result = await match_tool.ainvoke({"matchId": MATCH_ID})
            print(f"[Auth] set_match_id -> {str(result)[:200]}")
        except Exception as e:
            print(f"[Auth] set_match_id failed: {e}")


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

    # Auto-authenticate from token.txt (no LLM calls needed)
    if mcp_tools:
        await _auto_seed_auth(mcp_tools)

    app.state.agent = build_agent(extra_tools=mcp_tools if mcp_tools else None)

    # Warm up the model so first user request doesn't wait for disk load
    try:
        import httpx
        print(f"[Warmup] Pre-loading model '{MODEL}' into Ollama (CPU-only)...")
        async with httpx.AsyncClient(timeout=60) as client_:
            await client_.post(
                "http://localhost:11434/api/generate",
                json={"model": MODEL, "prompt": "hi", "stream": False, "options": {"num_gpu": 0}},
            )
        print(f"[Warmup] Model '{MODEL}' ready.")
    except Exception as e:
        print(f"[Warmup] Warning: could not pre-load model: {e}")

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
    thread_id: str | None = Field(default=None)


@app.post("/chat")
async def chat(request: ChatRequest):
    thread_id = request.thread_id or str(uuid.uuid4())
    try:
        result = await app.state.agent.ainvoke(
            {"messages": [HumanMessage(content=request.message)]},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
        )
        response = result["messages"][-1].content
        return {"response": response, "thread_id": thread_id}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)},
        )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE endpoint that streams agent progress (thinking, tool calls, final answer)."""
    thread_id = request.thread_id or str(uuid.uuid4())

    async def event_generator():
        try:
            yield {"event": "status", "data": json.dumps({"status": "thinking"})}
            agent_token_buffer = []

            async for event in app.state.agent.astream_events(
                {"messages": [HumanMessage(content=request.message)]},
                version="v2",
                config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
            ):
                kind = event.get("event")
                node = event.get("metadata", {}).get("langgraph_node", "")

                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if not (chunk and hasattr(chunk, "content") and chunk.content):
                        continue
                    if node == "agent":
                        # Buffer agent tokens — only flush if no tool calls follow
                        agent_token_buffer.append(chunk.content)
                    elif node == "reporter":
                        # Reporter tokens are always the clean final answer — stream immediately
                        yield {"event": "token", "data": json.dumps({"token": chunk.content})}

                elif kind == "on_chain_end" and node == "agent":
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict):
                        output_msgs = output.get("messages", [])
                        has_tool_calls = output_msgs and getattr(output_msgs[-1], "tool_calls", None)
                        if has_tool_calls:
                            # Discard buffer — it contains raw JSON tool call text
                            agent_token_buffer.clear()
                        else:
                            # No tool calls — agent answered directly, flush buffer
                            for token in agent_token_buffer:
                                yield {"event": "token", "data": json.dumps({"token": token})}
                            agent_token_buffer.clear()

                elif kind == "on_tool_start":
                    name = event.get("name", "unknown")
                    yield {"event": "tool_start", "data": json.dumps({"tool": name})}
                elif kind == "on_tool_end":
                    name = event.get("name", "unknown")
                    yield {"event": "tool_end", "data": json.dumps({"tool": name})}
                elif kind == "on_chain_start":
                    name = event.get("name", "")
                    if name == "reporter":
                        yield {"event": "status", "data": json.dumps({"status": "Summarising..."})}

            yield {"event": "done", "data": json.dumps({"status": "complete", "thread_id": thread_id})}
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

    # Convert full OpenAI message history to LangChain format.
    # Each request from Open WebUI includes the complete conversation, so we
    # pass it all and use a fresh thread_id (Open WebUI owns its own history).
    lc_messages = _openai_messages_to_langchain(messages)
    if not lc_messages:
        return JSONResponse(status_code=400, content={"error": "No messages provided"})

    # Fresh thread per request — Open WebUI sends full history each time
    thread_id = str(uuid.uuid4())

    if stream:
        return StreamingResponse(
            _openai_stream(lc_messages, thread_id),
            media_type="text/event-stream",
        )

    # Non-streaming
    try:
        result = await app.state.agent.ainvoke(
            {"messages": lc_messages},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
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


async def _openai_stream(lc_messages: list, thread_id: str):
    """Yield OpenAI-compatible SSE chunks from the LangGraph agent."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    sent_role = False
    try:
        async for event in app.state.agent.astream_events(
            {"messages": lc_messages},
            version="v2",
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
        ):
            kind = event.get("event")
            node = event.get("metadata", {}).get("langgraph_node", "")
            if kind == "on_chat_model_stream":
                # Only stream tokens from the agent node — planner/reporter must not leak
                if node != "agent":
                    continue
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

