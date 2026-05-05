# Slide Deck Plan: Building an AI Agent with LangGraph, MCP, and Local LLMs

## Purpose of This Document

This document is a complete brief for an AI agent (or a human) to generate a professional slide deck.
It contains all the context, narrative, technical details, slide-by-slide structure, and speaker notes
needed to build the presentation from scratch. No external context or code access is required.

---

## Presentation Overview

| Attribute | Value |
|---|---|
| **Title** | From Prompt to Production: Building a Personal AI Agent with LangGraph, MCP & Local LLMs |
| **Presenter** | Deepa Chandramohan (AI & Data practitioner, Accenture) |
| **Audience** | Technical peers and leaders interested in practical AI engineering |
| **Tone** | Practitioner storytelling — honest, hands-on, "I built this myself" |
| **Format** | ~20 slides, ~15–20 minutes |
| **Visual style** | Dark background (slate/navy), accent colour teal/cyan, code blocks in monospace. Clean and modern — not corporate template heavy. Include diagrams as described. |

---

## The Story This Deck Tells

This is NOT a theoretical AI talk. It is a first-person engineering story:

> *"I wanted an AI assistant that could search for job roles and apply to them automatically.
> Rather than use a cloud API, I built the entire thing locally — a small language model, a tool-calling
> agent, a custom MCP server, and a chat UI — all running on my laptop. Here's what I built, what broke,
> and what I learned."*

The arc is:
1. **The problem** — internal staffing portal (MySchedule) is manual and time-consuming
2. **The idea** — use AI to automate search and apply
3. **The stack** — local LLM + LangGraph agent + MCP tools + React UI
4. **The hard parts** — small LLMs hallucinate, tool-calling is unreliable, state is tricky
5. **The solution** — server-side bypass logic to guarantee correct tool execution
6. **What MCP is** — and why it matters for AI tool integration
7. **Live demo** — show it working end to end
8. **Lessons learned + what's next**

---

## Background Context (for the agent building slides)

### What is MySchedule?

MySchedule is an internal Accenture staffing portal where employees can find and apply for project roles.
It has a REST API authenticated via Azure AD (OAuth2). Applying to a role requires multiple sequential
API calls: search → view details → send email → record audit → create candidate → log indicator.

The presenter built a **Model Context Protocol (MCP) server** that wraps the MySchedule API into
discrete AI-callable tools. This MCP server is a Node.js/TypeScript process that communicates with
the AI agent over stdio using the MCP protocol.

### What is MCP (Model Context Protocol)?

MCP is an open standard (introduced by Anthropic, Nov 2024) that defines how AI models connect to
external tools, data sources, and services. It is analogous to USB-C for AI — a single protocol that
lets any AI client talk to any tool server without custom integration code.

Key concepts:
- **MCP Server**: a process that exposes a set of named tools with typed schemas
- **MCP Client**: the AI framework that discovers and calls those tools
- **Transport**: how they communicate — `stdio` (subprocess pipes) or HTTP/SSE
- The AI agent (LangGraph) uses `langchain-mcp-adapters` to connect to the MCP server and surface
  its tools as standard LangChain `Tool` objects

### What is LangGraph?

LangGraph is a library from LangChain for building stateful, multi-step AI agent workflows as graphs.
Each node in the graph is a function (e.g., "call the LLM", "run a tool"). Edges define routing
logic (e.g., "if the LLM called a tool, go to the tool node; otherwise, END").

Key features used:
- `StateGraph` — the graph definition
- `MemorySaver` — checkpoints conversation state per thread ID so context is preserved across turns
- Conditional edges — `should_continue` routes to either the tools node or END
- The agent loop: `agent node → should_continue → tools node → back to agent node → ...`

### What is the Local LLM Setup?

- **Model**: Microsoft `phi4-mini` (3.8B parameters, ~2.4 GB on disk)
- **Runtime**: [Ollama](https://ollama.com) — serves the model as a local REST API on port 11434
- **Hardware**: Intel Arc 140V GPU (Lunar Lake integrated) on a Windows laptop
- **Constraint**: phi4-mini runs CPU-only (`num_gpu=0`) due to Vulkan shared memory limits;
  achieves ~5–8 tokens/second
- The LangChain `ChatOllama` client connects to Ollama and presents the model as a standard
  LangChain chat model

### The MySchedule MCP Tools

The MCP server (`myschedule-mcp`) exposes these tools:

| Tool | Description |
|---|---|
| `search_roles` | Search for open roles by keyword, location, country, level, start date |
| `get_roles` | List all available roles (no filter) |
| `view_role` | Get full details for a role by ID — returns `projectKey`, `projectLocationKey`, contact email, description |
| `apply_role` | Submit an application — sends email, records audit, creates candidate, logs indicator (5 sequential API calls) |
| `seed_token` | Authenticate with an Azure AD access token (~1 hour validity) |
| `seed_refresh_token` | Authenticate with a refresh token (~90 day validity) |
| `set_match_id` | Set the user's profile match ID for personalised search results |
| `login` / `logout` | Browser-based auth (login avoided — triggers bot detection) |

### The Agent Architecture

```
User (React UI)
    │  HTTP POST /chat/stream (SSE)
    ▼
FastAPI Server (server.py, port 8000)
    │
    ├── [Bypass layer] — detects "yes"/confirm/JWT paste → handles directly without LLM
    │
    ▼
LangGraph Agent (agent.py)
    │  MemorySaver (per thread_id)
    ▼
 ┌──────────────────────────────────────┐
 │  agent node                          │
 │  (ChatOllama → phi4-mini via Ollama) │
 └──────┬───────────────────────────────┘
        │ tool_calls present?
        ├── YES → tools node (MCP tools via langchain-mcp-adapters)
        │              │
        │         MCP stdio transport
        │              ▼
        │         myschedule-mcp (Node.js, TypeScript)
        │              │ Azure AD auth
        │              ▼
        │         MySchedule REST API
        │
        └── NO → reporter node → END
```

### The Key Engineering Challenge: Small LLMs Can't Reliably Apply

The core technical problem: `phi4-mini` (and `qwen2.5:3b` before it) could search for roles but
**failed to reliably complete the multi-step apply flow**. Specifically:

1. Model would skip calling `view_role` (required to get `projectKey`/`projectLocationKey`)
2. Model would ask for confirmation, then on "yes" would **start a new search** instead of applying
3. Model would hallucinate tool call arguments — making up project keys that don't exist
4. After long conversations, the model would hallucinate entire responses without calling any tools

**The solution**: a **server-side bypass layer** in `server.py` that intercepts confirmation messages
and executes the apply flow directly (no LLM involvement):

- **Path 1**: Scan `MemorySaver` state for the last `view_role` ToolMessage → extract `projectKey`
  and `projectLocationKey` → call `apply_role` directly
- **Path 2** (fallback): Regex-extract the role ID from recent AI messages → call `view_role` then
  `apply_role` directly
- **Token interception**: If user pastes a JWT token in chat, intercept it server-side, save to
  `token.txt`, re-seed auth via MCP — model never sees the token

### The React UI

- Custom React chat interface (Create React App)
- Connects to FastAPI's `/chat/stream` endpoint using Server-Sent Events (SSE)
- Streams tokens in real-time as the agent responds
- Maintains conversation threads with persistent `thread_id` (maps to LangGraph `MemorySaver`)
- Critical bug fixed: React `setState` is async — `thread_id` was captured before state updates
  to prevent race conditions that caused every "yes" to start a fresh conversation

---

## Slide-by-Slide Structure

### SLIDE 1 — Title Slide

**Title**: From Prompt to Production  
**Subtitle**: Building a Personal AI Agent with LangGraph, MCP & a Local LLM  
**Presenter**: Deepa Chandramohan  
**Visual**: Dark background, a terminal/chat window mockup or circuit-board aesthetic. Possibly show
a chat conversation fragment: "Find data engineer roles in USA" → table of results → "Apply" → ✅

---

### SLIDE 2 — The Problem

**Title**: The Problem with Manual Staffing

**Content** (bullet points):
- Internal staffing portal (MySchedule) lists hundreds of open project roles
- Finding the right role requires repeated searching with different filters
- Applying requires: search → view details → confirm → email → audit → candidate record → indicator log
- This is ~10 minutes of manual work per application, repeated daily

**Visual**: A funnel or timeline showing the manual steps. Or a screenshot mock of a role listing table.

**Speaker note**: "I wanted to automate this. But I also wanted to learn: can a small, local LLM actually
handle real multi-step tool use? So I built the whole thing myself."

---

### SLIDE 3 — The Idea

**Title**: What If AI Could Do It?

**Content**:
- Goal: type "find data engineer roles in USA" → get a table of roles
- Type "apply" → AI searches, views details, and submits the application — automatically
- No cloud. No API keys. Everything runs locally on my laptop.
- Privacy: my resume, profile, and auth tokens never leave my machine

**Visual**: Simple before/after. Left: "You → Portal (manual, 10 min)". Right: "You → AI Agent → Portal (automatic, 30 sec)".

---

### SLIDE 4 — The Stack

**Title**: The Technology Stack

**Content** (3-column layout or icon grid):

| Layer | Technology | Role |
|---|---|---|
| Language Model | Microsoft phi4-mini (3.8B) | Understands intent, decides which tools to call |
| LLM Runtime | Ollama | Serves phi4-mini locally on port 11434 |
| Agent Orchestration | LangGraph | Stateful think→act→observe loop |
| AI Framework | LangChain | Connects LLM, tools, memory |
| Tool Protocol | Model Context Protocol (MCP) | Standard way to expose external tools to AI |
| Tool Server | Custom Node.js/TypeScript MCP server | Wraps MySchedule REST API |
| Backend | FastAPI (Python) | HTTP API + SSE streaming between UI and agent |
| Frontend | React | Chat interface |

**Visual**: Technology logo grid or layered architecture diagram (UI → FastAPI → LangGraph → Ollama → MCP → MySchedule)

**Speaker note**: "Everything except the MySchedule portal itself runs locally. Zero cloud spend."

---

### SLIDE 5 — What is MCP?

**Title**: Model Context Protocol — USB-C for AI Tools

**Content**:
- Open standard released by Anthropic in November 2024
- Defines how AI models connect to external tools and data sources
- Before MCP: every AI app needed custom integration code per tool
- With MCP: build a tool server once, any MCP-compatible AI client can use it
- Used by Claude Desktop, GitHub Copilot, Cursor, and now custom agents like this one

**Analogy block** (highlight box):  
> "USB-C let any device connect to any charger/display without custom cables.  
> MCP lets any AI model connect to any tool without custom code."

**Visual**: Split diagram. Left: "Old way" — tangled lines between AI apps and tools. Right: "MCP way" — clean hub-spoke with MCP in the middle.

---

### SLIDE 6 — The MySchedule MCP Server

**Title**: MCP Server: Wrapping MySchedule as AI Tools

**Content** (two columns):

**Left — What it is:**
- Node.js / TypeScript process
- Communicates with the AI agent over `stdio` (standard input/output pipes)
- Uses the official `@modelcontextprotocol/sdk`
- Authenticates to MySchedule using Azure AD OAuth2 tokens

**Right — Tools it exposes:**
- `search_roles` — keyword/location search
- `view_role` — full details including projectKey (required for apply)
- `apply_role` — 5-step apply: send email → audit → candidate → self-input → indicator
- `seed_token` / `seed_refresh_token` — auth management
- `set_match_id` — personalised search

**Visual**: A simple code snippet showing one MCP tool definition, e.g.:
```typescript
// view_role — returns projectKey needed for apply_role
{
  name: "view_role",
  description: "Get full details for a role by ID",
  inputSchema: { roleId: { type: "string" } }
}
```

---

### SLIDE 7 — What is LangGraph?

**Title**: LangGraph — Stateful Agent Workflows as Graphs

**Content**:
- Library from LangChain for building multi-step AI agents
- Define agent logic as a **directed graph**: nodes = functions, edges = routing logic
- Built-in **persistence** via MemorySaver — conversations are stateful across messages
- The loop: **think → act → observe → think again** until done

**Visual** (draw this as a flow diagram with boxes and arrows):

```
START
  ↓
[agent node]  ←──────────────────────┐
  │ (phi4-mini via Ollama)            │
  │ wants to call a tool?             │
  ├─── YES ──→ [tools node]           │
  │            (MCP tools)            │
  │            [ToolMessage back] ────┘
  │
  └─── NO ───→ [reporter node] → END
```

**Speaker note**: "The graph handles all the looping. I just define the nodes and routing logic.
MemorySaver means the agent remembers everything said in the conversation — across multiple messages."

---

### SLIDE 8 — The Full Architecture

**Title**: How Everything Connects

**Content**: Architecture diagram (the main visual of the talk)

```
┌─────────────────────────────────────────────────────────────────┐
│  Your Browser                                                    │
│  React Chat UI  ──── SSE stream ────→  FastAPI (port 8000)      │
└─────────────────────────────────────────────────────────────────┘
                                               │
                               ┌───────────────▼──────────────┐
                               │   server.py                   │
                               │   [Bypass Layer]              │
                               │   • JWT interception          │
                               │   • Confirmation bypass       │
                               └───────────────┬───────────────┘
                                               │
                               ┌───────────────▼──────────────┐
                               │   LangGraph Agent             │
                               │   MemorySaver (thread_id)     │
                               │   phi4-mini via ChatOllama    │
                               └──────┬───────────────────────┘
                                      │ tool calls
                 ┌────────────────────▼──────────────────────┐
                 │   MCP stdio transport                       │
                 │   langchain-mcp-adapters                    │
                 └────────────────────┬──────────────────────┘
                                      │
                 ┌────────────────────▼──────────────────────┐
                 │   myschedule-mcp (Node.js/TypeScript)       │
                 │   search_roles / view_role / apply_role     │
                 └────────────────────┬──────────────────────┘
                                      │ Azure AD auth
                 ┌────────────────────▼──────────────────────┐
                 │   MySchedule REST API                       │
                 │   (internal Accenture staffing portal)      │
                 └───────────────────────────────────────────┘
```

**Speaker note**: "Ollama runs in the background, also on your laptop. Everything in this diagram
is local — the only external call is to the MySchedule API itself."

---

### SLIDE 9 — The Hard Part: Small LLMs and Tool Reliability

**Title**: The Problem with Small Models

**Content** (2-column: "What we needed" vs "What actually happened"):

| What We Needed | What phi4-mini Did |
|---|---|
| Search → show table → wait | ✅ Worked reliably |
| User says "apply" → call `view_role` first | ❌ Often skipped `view_role`, made up projectKey |
| User says "yes" → call `apply_role` | ❌ Started a NEW search instead |
| Provide projectKey from `view_role` result | ❌ Hallucinated random numbers |
| Apply flow completes | ❌ Said "application submitted" without calling the tool |

**Key insight box**:  
> "A 3.8B parameter model is not reliable enough to orchestrate a 5-step apply flow.
> The solution: take the LLM out of the critical path for the apply step."

---

### SLIDE 10 — The Bypass Layer

**Title**: The Solution: Server-Side Bypass

**Content**:

The `server.py` layer intercepts messages **before** they reach the LLM and handles them deterministically:

**Trigger: user message is a confirmation ("yes", "confirm", "proceed")**

Path 1 — LLM already called `view_role`:
1. Read MemorySaver state for the current thread
2. Find the last `view_role` ToolMessage (real data, not hallucinated)
3. Extract `projectKey`, `projectLocationKey`, contact email
4. Call `apply_role` directly via MCP — no LLM involved

Path 2 — Fallback (LLM skipped `view_role`):
1. Regex-scan last 6 AI messages for a role ID
2. Call `view_role` to get real project keys
3. Call `apply_role` with verified data

**Bonus: JWT token interception**:
- If user pastes an Azure AD token into chat, intercept server-side
- Save to `token.txt`, re-seed MCP auth — model never sees the token

**Visual**: Simple flowchart: "User says 'yes'" → decision diamond "Is this a confirmation?" → YES path bypasses LLM, NO path goes to LLM.

**Speaker note**: "This is the key lesson: don't fight the model's limitations — work around them.
For deterministic multi-step flows, the server is more reliable than the LLM."

---

### SLIDE 11 — What the Apply Flow Actually Does

**Title**: Inside `apply_role` — 5 Steps in One Tool Call

**Content**:

When `apply_role` is called, the MCP server makes 5 sequential API calls to MySchedule:

```
Step 1: sendEmail         → Sends application email to staffing manager
Step 2: applyToRoleAudit  → Records the application in the audit log  
Step 3: createCandidate   → Creates candidate record in the portal
Step 4: saveCandidateSelfInput → Saves candidate's self-input data
Step 5: candidateIndicatorLogic → Logs the match indicator

Result: { success: true/false, data: { steps: [...], message: "..." } }
```

The result is formatted as:
- ✅ All 5 steps passed → "Application submitted"
- ⚠️ Partial success → shows which steps succeeded/failed
- ❌ Outright failure → validation or auth error message

**Visual**: A numbered list with step names and ✅ checkmarks. Or a horizontal pipeline diagram.

---

### SLIDE 12 — Authentication Design

**Title**: Authentication Without Storing Secrets

**Content**:

MySchedule uses Azure AD OAuth2. The solution handles auth at multiple levels:

| Mechanism | Duration | How Used |
|---|---|---|
| Access token (`token.txt`) | ~1 hour | Pasted from browser DevTools; auto-seeded at server startup |
| Refresh token (`refresh_token.txt`) | ~90 days | From browser localStorage; auto-seeded; preferred |
| In-chat token paste | Immediate | User pastes JWT → bypass intercepts → re-seeds without LLM seeing it |

**Security note**:
- `token.txt` and `refresh_token.txt` are in `.gitignore` — never committed
- `.webui_secret_key` was accidentally committed once — removed from git history via `git rm --cached`
- All auth is local; tokens never leave the machine

---

### SLIDE 13 — The SSE Streaming UI

**Title**: Real-Time Streaming with Server-Sent Events

**Content**:
- FastAPI uses `EventSourceResponse` (SSE) to stream agent progress in real time
- Events streamed: `status` (tool calls in progress), `token` (text chunks), `done` (thread_id)
- React UI listens on an `EventSource` connection, appends tokens as they arrive
- Thread persistence: each conversation has a `thread_id` that maps to LangGraph's MemorySaver
- Critical bug: React `setState` is async — `thread_id` must be captured as a local variable
  before any state updates (race condition fix)

**Visual**: Timeline of SSE events:
```
→ [status] "Searching for roles..."
→ [status] "Calling view_role..."  
→ [status] "Applying for Data Engineer..."
→ [token]  "✅ Application submitted — Role 6260189..."
→ [done]   { thread_id: "abc-123" }
```

---

### SLIDE 14 — Running on a Windows Laptop

**Title**: Local-First: Everything on Your Laptop

**Content**:

**Hardware**: Intel Core Ultra 7 258V (Lunar Lake), Intel Arc 140V GPU, 32 GB RAM

**Why CPU-only for the model**:
- Intel Arc 140V uses Vulkan backend (not CUDA)
- phi4-mini (2.4 GB) + 4096-token KV cache ≈ 2.6 GB exceeds Vulkan shared GPU memory limit
- Setting `num_gpu=0` runs on CPU — stable at ~5–8 tokens/second
- Enough for a personal assistant (not a production API)

**Service management** (`services.ps1`):
```powershell
.\services.ps1 start    # Start Ollama, Agent Server, Open WebUI
.\services.ps1 stop     # Stop agent server and Open WebUI
.\services.ps1 health   # Check all services
```

**Ports**:
- 11434 — Ollama (phi4-mini)
- 8000 — FastAPI agent server
- 3000 — React UI
- 8080 — Open WebUI (alternative interface)

---

### SLIDE 15 — Lessons Learned

**Title**: What I Learned Building This

**Content** (5 key lessons, one per bullet with a brief elaboration):

1. **Small LLMs are great at NLU, unreliable at multi-step execution**  
   phi4-mini understood intent well but couldn't reliably complete 5-step flows. Bypass the model for deterministic operations.

2. **MCP is genuinely useful — and easy to build**  
   Writing the MCP server took ~2 days. Once done, it worked with any MCP-compatible client (tried it with Claude Desktop too). The protocol is well-designed.

3. **State management is the hardest part of agent design**  
   LangGraph's MemorySaver + thread IDs solved persistence, but React's async state management caused subtle bugs. Every "yes" was going to a fresh conversation thread.

4. **Never fight your LLM's limitations — route around them**  
   The bypass layer was more impactful than any amount of prompt engineering. Deterministic code beats probabilistic text generation for multi-step workflows.

5. **Local AI is viable for personal automation**  
   A 3.8B model on consumer hardware, running offline, can handle real tasks. The privacy and cost benefits are significant.

---

### SLIDE 16 — What's Next

**Title**: Where This Goes Next

**Content** (two columns: Near-term and Future):

**Near-term**:
- Replace phi4-mini with `phi4` (14B) for better tool-calling reliability
- Add `refresh_token.txt` workflow for seamless 90-day auth
- Build an "applied roles" tracker — prevent duplicate applications
- Add role recommendation scoring based on skills match

**Future possibilities**:
- Multi-agent: separate "search agent" and "apply agent"
- Voice interface (Whisper for STT, piper-tts for TTS)
- Integrate with calendar to track start dates and follow-ups
- Expose this as an MCP server itself — let Claude Desktop or Copilot use it

---

### SLIDE 17 — Live Demo

**Title**: Let's See It Work

**Content** (demo script — slide is a prompt/cue card for presenter):

Demo flow to run live:
1. Open the React UI at `http://localhost:3000`
2. Type: **"Find data engineer roles in USA"**
   - Show: agent calls `search_roles`, returns a markdown table of roles
3. Type: **"Apply"** (referring to top result)
   - Show: bypass layer intercepts, calls `view_role`, then `apply_role`
   - Show: SSE status events streaming in real time
   - Show: ✅ Application submitted with step-by-step results
4. (Optional) Show server logs to demonstrate the bypass path ran, not the LLM

**Fallback if auth expired**:
- Paste a fresh JWT token into the chat
- Show: bypass intercepts, re-seeds auth, confirms ✅ Token updated

**Visual**: Blank/dark slide with just the title — the demo IS the content.

---

### SLIDE 18 — The Code

**Title**: It's All Open Source

**Content**:
- GitHub repo: `deepakungumaraj/local-llm-phi4`
- Key files:
  - `phi4-agent/server.py` — FastAPI + bypass layer + SSE streaming
  - `phi4-agent/agent.py` — LangGraph agent definition
  - `phi4-agent/instructions.md` — System prompt (tool rules, user profile, apply steps)
  - `services.ps1` — Start/stop all services
- MCP server: `myschedule-mcp` (separate repo, TypeScript)

**QR code or short URL** if available.

**Visual**: Code snippet — the heart of the bypass logic:
```python
if _is_confirmation(message):
    apply_params = _get_pending_apply(agent, thread_id)
    if apply_params:
        return EventSourceResponse(
            _apply_directly_generator(apply_params, thread_id, tool_map)
        )
```

---

### SLIDE 19 — Summary

**Title**: Summary

**Content** (one-liner per component):

| Component | What It Does |
|---|---|
| **phi4-mini + Ollama** | Local LLM — understands your intent, decides what to do |
| **LangGraph** | Orchestrates the think→act→observe agent loop with conversation memory |
| **MCP + myschedule-mcp** | Standard protocol + custom server — exposes MySchedule as AI tools |
| **FastAPI + bypass layer** | Handles streaming and guarantees correct apply execution |
| **React UI** | Real-time chat with SSE streaming |

**Closing statement**:  
> "AI isn't magic. It's an LLM, a graph, some tools, and a few hundred lines of Python.
> You can build this too — and you probably should."

---

### SLIDE 20 — Thank You / Q&A

**Title**: Questions?

**Content**:
- Deepa Chandramohan
- deepa.chandramohan@accenture.com
- GitHub: `deepakungumaraj/local-llm-phi4`

**Visual**: Same dark aesthetic as title slide. Optionally repeat the chat mockup from slide 1 — completing the visual loop.

---

## Design Notes for the Agent Building This

1. **Colour scheme**: Dark slate background (#1e2030 or similar), teal/cyan accents (#00d4ff), white body text, light grey subtitles. Code blocks: dark background with syntax highlighting.

2. **Diagrams**: Slides 7, 8, and 10 require flow diagrams. Render these as actual diagram visuals, not ASCII art. Use boxes with rounded corners, arrows, and colour-coded layers (UI = blue, Python = green, Node.js = orange, API = purple).

3. **Code blocks**: Use monospace font (Fira Code, JetBrains Mono, or similar). Keep snippets short (5–8 lines max per slide). Highlight the key line in a different colour.

4. **Tables**: Use alternating row shading. Header row in accent colour.

5. **Consistency**: Every slide should have a title (24–28pt), body content (16–18pt), and optionally a "key insight" callout box in a different colour/border.

6. **No clip art**: Tech-forward aesthetic. Use icons from a consistent icon set (e.g., Material Icons, Heroicons). Avoid generic stock photos.

7. **Slide numbers**: Bottom right corner, small.

8. **Presenter notes**: For slides 2, 7, 9, 10 — include the speaker note text as actual presenter notes in the slide deck file.
