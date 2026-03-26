import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    client = MultiServerMCPClient(MCP_SERVERS)
    mcp_tools = await client.get_tools()
    print(f"[MCP] Loaded {len(mcp_tools)} tools from MCP servers: "
          f"{[t.name for t in mcp_tools]}")
    app.state.agent = build_agent(extra_tools=mcp_tools)
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
        result = await app.state.agent.ainvoke({
            "messages": [HumanMessage(content=request.message)]
        })
        response = result["messages"][-1].content
        return {"response": response}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)},
        )


@app.get("/health")
def health():
    return {"status": "ok"}
