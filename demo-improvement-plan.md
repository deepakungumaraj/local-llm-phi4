# Demo Improvement Plan
**AI Staff Agent — local-llm-phi4 + myschedule-mcp**  
Deepa Chandramohan | May 2026

---

## Executive Summary

The system works and produces real results. What it lacks is *visibility* — the audience cannot see the intelligence happening, only the final answer. The single highest-leverage improvement is a live **agent trace panel** that shows every tool call, routing decision, and step in real time. Combined with a richer role card UI, a scripted "Day in My Life" demo narrative, and a model upgrade to `phi4-mini-reasoning`, the demo can go from "interesting chat app" to "this genuinely changes how work gets done."

---

## Priority Framework

Each item is tagged:

| Tag | Effort | When |
|-----|--------|------|
| **[QW]** Quick Win | < 4 hours | This week |
| **[MD]** Medium | 1–3 days | This month |
| **[BF]** Big Feature | 1–2 weeks | Next quarter |
| **[NR]** Narrative only | 0 code | Before the demo |

---

## 1. The Highest-Impact Change: Live Agent Trace Panel

**[MD] — Estimated: 1–2 days**

> "It's not faster, but it *feels* faster because we know what's happening."  
> — UX research on streaming AI interfaces ([prompt-kit.com](https://www.prompt-kit.com/chat-ui))

The current UI shows a spinner while the agent thinks, then shows the final answer. The audience sees a black box. Every high-impact AI demo — GitHub Copilot Workspace, Devin, Claude — works the same way: they make the *process* visible.

### What to build

Add a collapsible right-hand panel to the React UI that streams the agent's internal state in real time:

```
┌─────────────────────────────┬─────────────────────────────┐
│  Chat Window                │  Agent Trace                │
│                             │  (collapsible, right panel) │
│  > Find data engineer roles │                             │
│    in USA                   │  [agent]  thinking...       │
│                             │  [tool]   search_roles ▶    │
│  ⠋ Calling search_roles...  │    ├─ keywords: "data eng"  │
│                             │    ├─ location: "USA"       │
│                             │    └─ ✅ 3 results (0.8s)   │
│                             │  [reporter] synthesizing... │
│  ✅ Found 3 roles...         │  [done]   thread: abc-123  │
└─────────────────────────────┴─────────────────────────────┘
```

### Implementation

The SSE endpoint already emits `tool_start`, `tool_end`, `status`, and `done` events. The trace panel just needs to consume them differently from the chat window.

Add a `trace` event type to `server.py`:

```python
# Emit structured trace data on tool_start
yield {"event": "trace", "data": json.dumps({
    "node": "tool",
    "tool": name,
    "args": event.get("data", {}).get("input", {}),
    "ts": time.time()
})}
```

React side: render trace events as a timestamped sequence diagram.

### Why it works for demos

- Audience sees the AI *reasoning*, not just answering
- Makes the "bypass" pattern visible: "Watch — it skips the LLM here"
- Shows tool argument construction, proving the model understood intent
- Reveals latency breakdown: where time is spent (LLM vs API call)
- Referenced pattern: [AgentPrism](https://evilmartians.com/chronicles/debug-ai-fast-agent-prism-open-source-library-visualize-agent-traces) — open-source React sequence diagram library for agent traces

---

## 2. Role Cards — Replace Markdown Tables

**[MD] — Estimated: 1 day**

Currently, search results render as a raw markdown table. Tables work; cards *sell*.

### What to build

Replace the markdown table rendering with structured React components when the response contains role data:

```
┌─────────────────────────────────────────────────┐
│  🔵 Data Engineer                               │
│     BRISTOL MYERS SQUIBB  ·  New York, USA      │
│     Remote  ·  May 18 – Aug 24 2026             │
│     Role ID: 6260189                            │
│                                          [View] │
│                                         [Apply] │
└─────────────────────────────────────────────────┘
```

- Color-coded by location type: Remote = blue, Hybrid = orange, Onsite = grey
- `[Apply]` button sends "Apply for role 6260189" directly — no typing
- `[View]` sends "Show me details for role 6260189"
- Cards collapse into a horizontal scroll for multiple results

### Why it works for demos

- Audience immediately understands "this is a real result"
- One-click apply removes the awkward "now I need to type apply" gap in the demo flow
- Looks like a proper product, not a debug terminal

---

## 3. Applied Roles Tracker / Kanban Board

**[MD] — Estimated: 2 days**

> FoundRole (foundrole.com) offers a free kanban job tracker with MCP integration as of 2026.  
> We can build a lighter version natively in the UI.

### What to build

A second tab/page in the React app showing all applications submitted during the session:

```
APPLIED ROLES  (session tracker)
─────────────────────────────────────────────────────────────
Applied Today          │  Following Up           │  Closed
─────────────────────  │  ─────────────────────  │  ───────────
✅ Data Engineer        │                         │
   BMS · New York       │                         │
   Role 6260189         │                         │
   Applied 14:23        │                         │
─────────────────────────────────────────────────────────────
```

Backend: FastAPI stores applications in memory (or SQLite) per session. A new `GET /applications` endpoint returns the list. The `apply_role` success path already produces structured step results — append to this store.

### Bonus: "Have I already applied?" guard

Before the agent calls `apply_role`, check the tracker. If the role is already in the "Applied" column, surface a warning instead of re-applying.

### Why it works for demos

- Proves the system is producing real, tracked output — not just chat
- "Look — everything I applied for today is here" is a powerful closing moment
- Shows the agent as a *workflow tool*, not a chatbot

---

## 4. Model Upgrade — phi4-mini-reasoning

**[MD] — Estimated: half a day to benchmark**

The current `phi4-mini:latest` is reliable for search but struggles with multi-step planning. Microsoft released a specialized variant:

> **phi4-mini-reasoning** — designed for multi-step, logic-intensive tasks.  
> Better at chained reasoning, tool sequencing, and instruction following than base phi4-mini.  
> ([ollama.com/library/phi4-mini-reasoning](https://ollama.com/library/phi4-mini-reasoning))

### What to test

```powershell
ollama pull phi4-mini-reasoning
# Change OLLAMA_MODEL=phi4-mini-reasoning in environment
# Run 10 test prompts and compare:
# - Does it output structured tool_calls (reducing need for text parser)?
# - Does it call view_role before apply_role reliably?
# - Does "yes" routing work without the bypass?
```

If it's better at structured tool calls, the text-call parser fallback becomes less critical — simplifying the agent significantly.

### Longer-term: phi4 (14B)

- ~8–10 GB RAM requirement — tight on 32 GB shared but feasible
- Dramatically better tool-call reliability based on benchmarks
- Would allow reducing or removing the server-side bypass
- Test with: `ollama pull phi4` and `num_gpu=0`

### Alternative: Qwen3

> Qwen3 has emerged as a strong alternative to phi4 for edge agent deployments in 2026, with better multilingual and tool-call performance at similar parameter counts.  
> ([localaimaster.com](https://localaimaster.com/blog/small-language-models-guide-2026))

---

## 5. Skills-Based Role Match Scoring

**[BF] — Estimated: 3–5 days**

### The idea

Add a `match_score` tool or embed scoring into `search_roles` results by comparing each role's required skills against a local profile (Deepa's skills list stored as a text file or vector embedding).

### Implementation sketch

```python
# skills_profile.txt — stored locally, never leaves machine
"""
Skills: Python, FastAPI, LangChain, LangGraph, TypeScript, Azure,
        Data Engineering, ML/AI, React, REST APIs, Financial Services
Level: Senior / Lead
Preferred: Remote, hybrid
Available: From June 2026
"""
```

On each `search_roles` result, embed the role description and the skills profile with a local embedding model (`nomic-embed-text` via Ollama), compute cosine similarity, and surface as a `Match: 87%` badge on each role card.

```powershell
ollama pull nomic-embed-text  # ~275 MB, fast
```

Vector store: `chromadb` in-memory, rebuilt from profile on startup.

### Why it works for demos

- Changes the narrative from "I searched" to "AI ranked for me"
- A "Match: 94%" badge on a relevant role is a compelling visual
- Directly comparable to LinkedIn's AI recruiter feature (which does the same)
- Referenced implementation: [DEV Community — RAG to Multi-Agent AI for Job Matching](https://dev.to/reebow/from-rag-to-multi-agent-ai-for-job-matching-5d66)

---

## 6. "Compare Roles" Capability

**[QW] — Estimated: 2–3 hours**

Add a system-prompt instruction and a new prompt suggestion so the user can say:

> "Compare roles 6260189 and 6182047 — which is better for me?"

The agent calls `view_role` twice, then the reporter synthesizes a comparison table. No new tools needed — this works today with careful prompting. The change is:

1. Add a suggested prompt chip in the UI: **"Compare top 2 roles"**
2. Update `instructions.md` to include an example of comparison reasoning
3. The reporter already formats markdown tables — it will produce a comparison naturally

### Demo script use

Show this after the initial search: "Now watch — I can compare them." It makes the system feel intelligent, not just capable.

---

## 7. Demo Setup: Mock / Safe Mode

**[QW] — Estimated: 2 hours**

Live demos that submit real job applications to real systems carry risk. Add a `DEMO_MODE=true` environment variable that:

- Intercepts `apply_role` calls and returns a fake success response
- Logs "DEMO MODE: would have submitted application for role X" to console
- Shows a faint `[DEMO MODE]` badge in the UI header

This allows showing the full apply flow to audiences without actually submitting applications.

```python
# server.py addition
if os.environ.get("DEMO_MODE") == "true":
    yield {"event": "token", "data": json.dumps({
        "token": "✅ [DEMO MODE] Application simulated — Role 6260189 at BRISTOL MYERS SQUIBB\n\n"
                 "✅ sendEmail — simulated\n✅ applyToRoleAudit — simulated\n"
                 "✅ createCandidate — simulated\n✅ saveCandidateSelfInput — simulated\n"
                 "✅ candidateIndicatorLogic — simulated"
    })}
    return
```

---

## 8. Services Health Dashboard

**[QW] — Estimated: 2 hours**

Add a small `/health` page to the React UI (accessible from a button in the header) that shows:

```
Service Status
──────────────────────────────────────
✅ Ollama (phi4-mini)    11434   246ms
✅ FastAPI agent          8000    12ms
✅ MCP myschedule-mcp    stdio  connected
✅ MySchedule API        auth    refresh token valid (~82 days left)
──────────────────────────────────────
Last checked: 2 seconds ago  [Refresh]
```

FastAPI already has `/health`. Add:
- `GET /health/detailed` that checks Ollama, MCP connectivity, and token expiry
- React polling this every 30 seconds, showing a green/red dot in the header

### Why it works for demos

- Opening the demo with green lights everywhere sets confidence
- "Watch the MCP connection light" — audience can see the integration
- Token expiry warning prevents mid-demo auth failures ("72 hours left")

---

## 9. Before/After Timer in the Demo

**[NR] — No code required**

During the live demo, open two browser tabs side by side on the projector:

- **Left tab:** MySchedule portal logged in, on the search page
- **Right tab:** The AI agent chat window

Start a visible timer (phone stopwatch on screen). Demonstrate the manual process on the left while explaining it takes ~10 minutes. Then switch to the agent tab, type the search, apply — and stop the timer at ~30 seconds.

This is the most powerful demo technique that requires zero code — pure narrative storytelling. Research consistently shows before/after comparisons are the highest-impact demo format.

---

## 10. "Explain Your Reasoning" Command

**[QW] — Estimated: 1–2 hours**

Add a prompt suggestion chip: **"Why did you choose that role?"**

When the user asks this after a search, the agent explains:
- Which filters it used
- Which results it ranked highest and why
- What it noticed about the role details

This already works via prompting — the key is surfacing it as an easy-to-click suggestion in the UI. It makes the agent feel *intelligent* rather than mechanical.

---

## 11. Proactive Daily Digest (Future / BF)

**[BF] — Estimated: 1 week**

A background task that runs at 9 AM daily:

1. Agent calls `search_roles` with saved search criteria (stored in a local JSON file)
2. Filters out roles already in the applied tracker
3. Sends a Windows toast notification (via `win10toast` or `plyer`) with new matches
4. When clicked, opens the chat with pre-filled context: "Here are today's new matching roles"

This transforms the system from reactive (user asks) to proactive (agent monitors).

---

## 12. OpenAI API Compatibility — Demo via Open WebUI

**[QW] — Already implemented, just needs showcasing**

The FastAPI server already exposes `/v1/chat/completions`. This means:

> **Open WebUI** — the most polished open-source chat UI — already works with this agent out of the box.

For a demo to a less technical audience, Open WebUI (port 8080) looks more like a professional product than the custom React UI. Consider:

- Starting Open WebUI as part of the demo stack
- Showing the demo in Open WebUI for visual impact
- Then switching to the React UI to show the streaming trace panel

```powershell
# One-liner to start Open WebUI connected to this agent
docker run -d -p 8080:8080 -e OPENAI_API_BASE_URL=http://localhost:8000/v1 ghcr.io/open-webui/open-webui:main
```

---

## 13. Narrative: "Day in My Life" Demo Script

**[NR] — No code required**

The most compelling demo structure is a personal story, not a feature walkthrough. Proposed script:

---

**ACT 1 — The Problem (30 seconds)**
> "Every morning, I check MySchedule for new project roles. I open it, search, filter, read each one, fill in the application form — email, project key, my CV links. For each role, that's 10 minutes. And there are 20 new roles every week."

**ACT 2 — The Magic (2 minutes)**
> "So I built an AI agent that does this for me."  
> *[Type in chat: "Find data engineer roles in USA starting in May"]*  
> *[Watch trace panel light up — tool_start → results]*  
> *[Role cards appear with match scores]*  
> "It found three. This one — Bristol Myers Squibb — 94% match."  
> *[Click Apply button on card]*  
> "Done. Application submitted. 28 seconds."

**ACT 3 — The Why (30 seconds)**
> "Everything ran on my laptop. No cloud. No API keys. My data, my credentials, never left this machine. And the technology stack — LangGraph, MCP — is the same one LinkedIn uses for their AI recruiter."

**ACT 4 — The So What (30 seconds)**
> "In the time it takes to manually apply for one role, I can apply for twenty. And I didn't build this in months — it took two weeks, using open-source tools that are available to anyone."

---

## 14. Expose Agent as an MCP Server (Future / BF)

**[BF] — Estimated: 1 week**

The agent currently *consumes* MCP. It could also *expose* MCP — allowing Claude Desktop, GitHub Copilot, or any other MCP client to use it as a tool.

Imagine: from Claude Desktop, saying "search for roles and apply for the best match" — and this agent handles it.

This would be the most technically impressive thing to demo: a recursive system where one AI model calls another AI agent via MCP, which then calls the staffing portal.

---

## 15. Small UI Polish Items

**[QW] — Each < 1 hour**

| Item | What | Why |
|------|------|-----|
| Dark mode header | Add "AI Staff Agent" logo/wordmark to chat header | Looks like a product, not a dev tool |
| Animated tool status | Pulse animation on "Calling search_roles..." | Makes waiting feel active |
| Markdown copy button | Copy button on each message | Practical; audience asks for it |
| Thread ID display | Show current thread_id in footer | Proves conversation memory is real |
| Mobile responsive | CSS media queries for phone view | Demo via phone in audience mode |
| Error toast | Replace raw "Error connecting to agent" with styled toast | Professional feel |
| Suggested prompts | 3–4 clickable prompt chips on first load | Lowers barrier to first interaction |

---

## Recommended Priority Order for Demo Prep

### Do this week (before any demo)

1. **[NR] Write and rehearse the "Day in My Life" demo script** — no code, highest ROI
2. **[QW] Add a DEMO_MODE flag** — never accidentally submit real applications during demos
3. **[QW] Build the services health dashboard** — confidence-building visual before the demo starts
4. **[QW] Add suggested prompt chips** — reduces awkward "what do I type?" moments
5. **[MD] Build the agent trace panel** — makes the intelligence visible; most powerful change

### Do this month (for recurring demos)

6. **[MD] Role cards** — replaces markdown tables, looks like a product
7. **[MD] Benchmark phi4-mini-reasoning** — may improve reliability without the bypass
8. **[MD] Applied roles tracker / Kanban** — proves the agent produces persistent output
9. **[QW] "Compare roles" prompt** — shows multi-step reasoning capability
10. **[QW] "Explain your reasoning" prompt** — makes agent feel intelligent

### Future (for a polished showcase)

11. **[BF] Skills-based match scoring** — changes narrative from "search" to "AI ranked for me"
12. **[BF] Proactive daily digest** — shows the agent as a background worker, not just a chatbot
13. **[BF] Expose as MCP server** — technically impressive, recursive AI-to-AI demo moment

---

## References

- [AgentPrism — open-source React library for visualizing agent traces](https://evilmartians.com/chronicles/debug-ai-fast-agent-prism-open-source-library-visualize-agent-traces)
- [prompt-kit — React components for AI chat UIs](https://www.prompt-kit.com/chat-ui)
- [phi4-mini-reasoning — Ollama model page](https://ollama.com/library/phi4-mini-reasoning)
- [phi4 (14B) — Ollama model page](https://ollama.com/library/phi4)
- [Building AI Agents on edge devices with Phi-4-mini function calling (Microsoft)](https://techcommunity.microsoft.com/blog/educatordeveloperblog/building-ai-agents-on-edge-devices-using-ollama--phi-4-mini-function-calling/4391029)
- [FoundRole — Kanban job tracker with MCP integration](https://www.foundrole.com/job-tracker)
- [DEV Community — From RAG to Multi-Agent AI for Job Matching](https://dev.to/reebow/from-rag-to-multi-agent-ai-for-job-matching-5d66)
- [InfoWorld — Best practices for building agentic systems](https://www.infoworld.com/article/4154570/best-practices-for-building-agentic-systems.html)
- [LangChain — LangGraph Agent Orchestration](https://www.langchain.com/langgraph)
- [LangSmith — AI observability and tracing](https://www.langchain.com/langsmith/observability)
- [Ontotext — Matching Skills and Candidates with Graph RAG](https://www.ontotext.com/blog/matching-skills-and-candidates-with-graph-rag/)
