import asyncio
import json
import os
import re
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

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
    app.state.mcp_tool_map = {t.name: t for t in mcp_tools}

    # Warm up the model so first user request doesn't wait for disk load
    try:
        import httpx
        print(f"[Warmup] Pre-loading model '{MODEL}' into Ollama (GPU)...")
        async with httpx.AsyncClient(timeout=60) as client_:
            await client_.post(
                "http://localhost:11434/api/generate",
                json={"model": MODEL, "prompt": "hi", "stream": False, "options": {"num_gpu": 0, "num_ctx": 4096}},
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

# ──────────────────────────────────────────────────────────────────────
# Server-side apply bypass — completely avoids the unreliable small model
# for the multi-step confirmation flow.
# ──────────────────────────────────────────────────────────────────────

# User profile constants (used when calling apply_role directly)
_PROFILE_KEY = 1941983
_ENTERPRISE_ID = "deepa.chandramohan"
_CANDIDATE_NAME = "Chandramohan, Deepa."
_COPY_TO_EMAIL = "deepa.chandramohan@accenture.com"
_USER_NAME = "Deepa"
_ONE_PAGER_CV_URL = "https://wd103.myworkday.com/accenture/email-universal/inst/21037$150134/rel-task/2998$33471.htmld"
_DIGITAL_CV_URL = "https://wd103.myworkday.com/accenture/d/inst/1$247/247$1983301.htmld#TABINDEX=1&SUBTABINDEX=1"

_CONFIRM_WORDS = {"yes", "confirm", "proceed", "go ahead", "do it", "apply", "submit", "ok", "sure", "yep", "yeah"}


def _is_confirmation(text: str) -> bool:
    return text.strip().lower().rstrip("!.") in _CONFIRM_WORDS


def _fmt_date(date_str: str) -> str:
    """Convert ISO date (2026-05-18 or 2026-05-18T...) to DD-Mon-YYYY."""
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d-%b-%Y")
    except (ValueError, TypeError):
        return date_str or ""


def _parse_project_name(raw: str) -> tuple[str, str]:
    """Parse 'WBS - ProjectName / City' → (projectNumber, projectName)."""
    if " - " in raw:
        parts = raw.split(" - ", 1)
        wbs = parts[0].strip()
        name = parts[1].split(" / ")[0].strip()
        return wbs, name
    return "", raw


def _extract_tool_content(result) -> str:
    """Extract plain text from a tool result — handles both string and MCP list-of-blocks format."""
    # Result itself may be a list of content blocks (direct MCP return)
    if isinstance(result, list):
        parts = [item.get("text", "") for item in result if isinstance(item, dict)]
        return "\n".join(parts)
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    if isinstance(content, list):
        # MCP format: [{'type': 'text', 'text': '...'}]
        parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        return "\n".join(parts)
    return str(content)



def _extract_apply_params(role: dict) -> dict:
    """Build apply_role parameters from a view_role RoleDetail dict."""
    proj_raw = role.get("projectName", "")
    proj_number, proj_name = _parse_project_name(proj_raw)
    contact_email = role.get("contactEmail", "")
    to_emails = [contact_email] if contact_email else []
    return {
        "roleId": int(role.get("id", 0)),
        "profileKey": _PROFILE_KEY,
        "projectKey": int(role.get("projectKey") or 0),
        "projectLocationKey": int(role.get("projectLocationKey") or 0),
        "enterpriseId": _ENTERPRISE_ID,
        "candidateName": _CANDIDATE_NAME,
        "roleTitle": role.get("title", ""),
        "projectName": proj_name,
        "projectNumber": proj_number,
        "clientName": role.get("client", ""),
        "roleStartDate": _fmt_date(role.get("startDate", "")),
        "roleEndDate": _fmt_date(role.get("endDate", "")),
        "toEmails": to_emails,
        "copyToEmail": _COPY_TO_EMAIL,
        "onePagerCVUrl": _ONE_PAGER_CV_URL,
        "digitalCVUrl": _DIGITAL_CV_URL,
        "userName": _USER_NAME,
    }


def _get_pending_apply(agent, thread_id: str) -> dict | None:
    """Scan conversation history for the last view_role ToolMessage and extract apply params."""
    try:
        state = agent.get_state({"configurable": {"thread_id": thread_id}})
        msgs = state.values.get("messages", [])
        for m in reversed(msgs):
            if getattr(m, "name", None) == "view_role" and getattr(m, "content", None):
                try:
                    raw = _extract_tool_content(m)
                    parsed = json.loads(raw)
                    role = parsed.get("role") if isinstance(parsed, dict) else None
                    if role and role.get("id"):
                        params = _extract_apply_params(role)
                        print(f"[PendingApply] Found view_role result for thread={thread_id} "
                              f"role={params['roleId']} proj={params['projectKey']}")
                        return params
                except (json.JSONDecodeError, Exception) as e:
                    print(f"[PendingApply] parse error: {e}")
    except Exception as e:
        print(f"[PendingApply] state read error: {e}")
    return None


def _format_apply_result(content: str, role_id, title: str, client: str) -> str:
    """Format apply_role response into a human-readable message.

    Handles three cases from applyRole.ts:
    - success=true  → all steps passed
    - success=false + data.steps → partial success (some steps failed)
    - success=false + error      → outright failure (validation / auth error)
    """
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, Exception):
        return f"✅ Application submitted for Role {role_id}.\n\n{content}"

    if not isinstance(parsed, dict):
        return f"✅ Application submitted for Role {role_id}.\n\n{content}"

    steps = parsed.get("data", {}).get("steps", [])
    step_lines = "\n".join(
        f"{'✅' if s.get('success') else '❌'} {s['step']}: {s['message']}"
        for s in steps
    )

    if parsed.get("success"):
        return f"✅ **Application submitted — Role {role_id}: {title} at {client}**\n\n{step_lines}"

    if steps:
        # Partial: some steps succeeded (e.g. email sent but indicator failed)
        partial_msg = parsed.get("data", {}).get("message", "")
        return f"⚠️ **Application partially submitted — Role {role_id}: {title} at {client}**\n\n{step_lines}\n\n{partial_msg}"

    # Outright failure (validation error, auth error, etc.)
    return f"❌ Application failed: {parsed.get('error', content)}"


async def _apply_directly_generator(apply_params: dict, thread_id: str, tool_map: dict):
    """SSE generator that calls apply_role directly, bypassing the LLM."""
    role_id = apply_params.get("roleId")
    title = apply_params.get("roleTitle", "")
    client = apply_params.get("clientName", "")
    try:
        yield {"event": "status", "data": json.dumps({"status": f"Applying for {title}..."})}
        apply_tool = tool_map.get("apply_role")
        if not apply_tool:
            yield {"event": "error", "data": json.dumps({"detail": "apply_role tool not available"})}
            return
        print(f"[Apply] Calling apply_role directly for role={role_id} params={apply_params}")
        apply_result = await apply_tool.ainvoke(apply_params)
        content = _extract_tool_content(apply_result)
        # Try to extract a clean success/failure message from the JSON result
        msg = _format_apply_result(content, role_id, title, client)
        yield {"event": "token", "data": json.dumps({"token": msg})}
    except Exception as e:
        traceback.print_exc()
        yield {"event": "error", "data": json.dumps({"detail": str(e)})}
    finally:
        yield {"event": "done", "data": json.dumps({"status": "complete", "thread_id": thread_id})}

def _extract_role_id_from_messages(agent, thread_id: str) -> str | None:
    """Scan the last few AI messages for a role ID mentioned in text."""
    try:
        state = agent.get_state({"configurable": {"thread_id": thread_id}})
        msgs = state.values.get("messages", [])
        # Check last 6 messages for an AI message mentioning a Role ID
        for m in reversed(msgs[-6:]):
            if not (hasattr(m, "content") and isinstance(m.content, str)):
                continue
            # Match "Role ID: 6260189" in any markdown formatting (**Role ID:** 6260189, etc.)
            match = re.search(r'[Rr]ole\b[^\n]*?(\d{6,8})\b', m.content)
            if match:
                role_id = match.group(1)
                print(f"[PendingApply] Extracted role ID={role_id} from AI message")
                return role_id
        print(f"[PendingApply] No role ID found in last 6 messages for thread={thread_id}")
    except Exception as e:
        print(f"[PendingApply] role_id extraction error: {e}")
    return None


async def _view_and_apply_generator(role_id: str, thread_id: str, tool_map: dict):
    """Call view_role then apply_role directly, streaming status updates."""
    try:
        view_tool = tool_map.get("view_role")
        apply_tool = tool_map.get("apply_role")
        if not view_tool or not apply_tool:
            yield {"event": "error", "data": json.dumps({"detail": "Required tools not available"})}
            return

        yield {"event": "status", "data": json.dumps({"status": f"Looking up role {role_id}..."})}
        print(f"[Apply] Calling view_role for role_id={role_id}")
        view_result = await view_tool.ainvoke({"roleId": str(role_id)})
        view_content = _extract_tool_content(view_result)

        try:
            parsed = json.loads(view_content)
            role = parsed.get("role") if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, Exception):
            role = None

        if not role or not role.get("id"):
            yield {"event": "error", "data": json.dumps(
                {"detail": f"Could not retrieve role details for {role_id}: {view_content[:300]}"}
            )}
            return

        apply_params = _extract_apply_params(role)
        title = apply_params.get("roleTitle", "")
        client = apply_params.get("clientName", "")

        yield {"event": "status", "data": json.dumps({"status": f"Applying for {title}..."})}
        print(f"[Apply] Calling apply_role for role={role_id} proj={apply_params['projectKey']}")
        apply_result = await apply_tool.ainvoke(apply_params)
        content = _extract_tool_content(apply_result)

        msg = _format_apply_result(content, role_id, title, client)
        yield {"event": "token", "data": json.dumps({"token": msg})}
    except Exception as e:
        traceback.print_exc()
        yield {"event": "error", "data": json.dumps({"detail": str(e)})}
    finally:
        yield {"event": "done", "data": json.dumps({"status": "complete", "thread_id": thread_id})}


_JWT_RE = re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


def _extract_token(text: str) -> str | None:
    m = _JWT_RE.search(text)
    return m.group(0) if m else None


async def _reseed_auth(token: str) -> str:
    """Save token to token.txt and re-seed auth via MCP tools. Returns status message."""
    try:
        token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(token.strip())
        print(f"[Auth] Saved new token to token.txt ({len(token)} chars)")
    except Exception as e:
        print(f"[Auth] Failed to save token: {e}")

    tool_map = app.state.mcp_tool_map
    seed_tool = tool_map.get("seed_token")
    if not seed_tool:
        return "❌ seed_token tool not available"
    try:
        result = await seed_tool.ainvoke({"token": token})
        content = _extract_tool_content(result)
        await _set_match_id(tool_map)
        print(f"[Auth] Re-seeded token: {content[:100]}")
        return f"✅ Token updated. You are now authenticated — try your request again."
    except Exception as e:
        return f"❌ Failed to re-seed token: {e}"


async def _token_update_generator(token: str, thread_id: str):
    """SSE generator that re-seeds auth from a pasted JWT."""
    yield {"event": "status", "data": json.dumps({"status": "Updating token..."})}
    msg = await _reseed_auth(token)
    yield {"event": "token", "data": json.dumps({"token": msg})}
    yield {"event": "done", "data": json.dumps({"status": "complete", "thread_id": thread_id})}



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
    message = request.message

    # Intercept token paste — bypass LLM entirely, re-seed auth directly
    token = _extract_token(message)
    if token and len(token) > 100:
        print(f"[Bypass] JWT detected in message — re-seeding auth")
        return EventSourceResponse(_token_update_generator(token, thread_id))

    # Bypass the LLM entirely when confirming — read view_role result from state and apply directly
    if _is_confirmation(message):
        print(f"[Bypass] Confirmation detected: '{message}' thread={thread_id}")
        # Path 1: model already called view_role → use that result
        apply_params = _get_pending_apply(app.state.agent, thread_id)
        if apply_params:
            return EventSourceResponse(
                _apply_directly_generator(apply_params, thread_id, app.state.mcp_tool_map)
            )
        # Path 2: model skipped view_role but mentioned a role ID → fetch it ourselves
        role_id = _extract_role_id_from_messages(app.state.agent, thread_id)
        if role_id:
            return EventSourceResponse(
                _view_and_apply_generator(role_id, thread_id, app.state.mcp_tool_map)
            )
        print(f"[Bypass] No role found — falling through to LLM")

    async def event_generator():
        try:
            yield {"event": "status", "data": json.dumps({"status": "thinking"})}
            agent_token_buffer = []

            async for event in app.state.agent.astream_events(
                {"messages": [HumanMessage(content=message)]},
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
                    tool_input = event.get("data", {}).get("input", {})
                    yield {"event": "tool_start", "data": json.dumps({"tool": name})}
                    # Emit structured trace event per the demo plan
                    yield {"event": "trace", "data": json.dumps({
                        "node": "tool",
                        "tool": name,
                        "args": tool_input,
                        "ts": time.time()
                    })}
                elif kind == "on_tool_end":
                    name = event.get("name", "unknown")
                    tool_output = event.get("data", {}).get("output", None)
                    yield {"event": "tool_end", "data": json.dumps({"tool": name})}
                    # Emit trace event showing tool completion
                    yield {"event": "trace", "data": json.dumps({
                        "node": "tool_end",
                        "tool": name,
                        "result": tool_output if isinstance(tool_output, (str, dict, list)) else str(tool_output),
                        "ts": time.time()
                    })}
                elif kind == "on_chain_start":
                    name = event.get("name", "")
                    if name == "agent":
                        # Emit trace for agent thinking
                        yield {"event": "trace", "data": json.dumps({
                            "node": "agent",
                            "status": "thinking...",
                            "ts": time.time()
                        })}
                    elif name == "reporter":
                        # Emit trace for reporter synthesizing
                        yield {"event": "trace", "data": json.dumps({
                            "node": "reporter",
                            "status": "synthesizing...",
                            "ts": time.time()
                        })}
                        yield {"event": "status", "data": json.dumps({"status": "Summarising..."})}

            # Emit completion trace event
            yield {"event": "trace", "data": json.dumps({
                "node": "done",
                "thread_id": thread_id,
                "ts": time.time()
            })}
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

