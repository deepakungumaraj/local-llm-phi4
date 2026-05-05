# Switching from Local Ollama to Azure Foundry Models

## Overview
To use Azure models instead of local Ollama, you'll switch from `ChatOllama` to `AzureChatOpenAI` (or `AzureOpenAI` for the base class).

Azure offers two main options:
1. **Azure OpenAI** - Managed OpenAI models (GPT-4, GPT-3.5-turbo, etc.)
2. **Azure AI Foundry** - Broader model selection including open models

---

## Step 1: Install Required Dependencies

```bash
pip install langchain-openai
# Already have langchain installed from existing setup
```

---

## Step 2: Set Up Azure Credentials

Get these from your Azure portal:

### Azure OpenAI Setup:
```bash
# Set environment variables
$env:AZURE_OPENAI_API_KEY = "your-api-key"
$env:AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
$env:AZURE_OPENAI_API_VERSION = "2024-02-15-preview"
```

### Azure AI Foundry Setup:
```bash
# Same as above - Foundry uses the same endpoint infrastructure
$env:AZURE_OPENAI_API_KEY = "your-foundry-key"
$env:AZURE_OPENAI_ENDPOINT = "https://your-project.openai.azure.com/"
$env:AZURE_OPENAI_API_VERSION = "2024-05-01-preview"  # Might be newer
```

---

## Step 3: Modify agent.py

### Current (Ollama):
```python
from langchain_ollama import ChatOllama

MODEL = os.environ.get("OLLAMA_MODEL", "phi4-mini:latest")
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

llm = ChatOllama(
    model=MODEL,
    timeout=180,
    num_ctx=4096,
    num_gpu=0
)
```

### Switch to Azure OpenAI:
```python
from langchain_openai import AzureChatOpenAI

# For Azure OpenAI (managed by Microsoft)
MODEL = os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4")  # Your deployment name in Azure

llm = AzureChatOpenAI(
    model=MODEL,
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    temperature=0,
    max_tokens=4096
)
```

### Switch to Azure AI Foundry (for open models):
```python
from langchain_openai import AzureChatOpenAI

# For Azure AI Foundry (Mistral, Llama, Phi, etc.)
MODEL = os.environ.get("AZURE_DEPLOYMENT_NAME", "Phi-4")  # Deployment name in Foundry

llm = AzureChatOpenAI(
    model=MODEL,
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
    temperature=0,
    max_tokens=4096
)
```

---

## Step 4: Remove/Update Ollama-Specific Code

Remove the Ollama recovery function (lines 25-42 in agent.py):

```python
# DELETE THIS ENTIRE FUNCTION - it's Ollama-specific
async def _reset_ollama_runner():
    """Unload and reload the model to recover from a Vulkan runner crash."""
    ...
```

Remove the Ollama warmup call in server.py (around line 120):

```python
# DELETE THIS - it's Ollama-specific
print(f"[Warmup] Pre-loading model '{MODEL}' into Ollama (GPU)...")
async with httpx.AsyncClient(timeout=60) as client_:
    await client_.post(
        "http://localhost:11434/api/generate",
        json={"model": MODEL, "prompt": "hi", "stream": False, "options": {"num_gpu": 0, "num_ctx": 4096}},
    )
```

---

## Step 5: Environment Configuration

Create or update `.env` file (or use PowerShell):

### For Azure OpenAI:
```bash
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_DEPLOYMENT_NAME=gpt-4
```

### For Azure AI Foundry:
```bash
AZURE_OPENAI_API_KEY=your-foundry-key
AZURE_OPENAI_ENDPOINT=https://your-project.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-05-01-preview
AZURE_DEPLOYMENT_NAME=Phi-4
```

---

## Comparison: Ollama vs Azure

| Aspect | Ollama | Azure OpenAI | Azure AI Foundry |
|--------|--------|--------------|------------------|
| **Cost** | Free (local) | Pay per token | Pay per token |
| **Latency** | Very low (local) | ~100ms | ~100ms |
| **Models** | Limited (Phi, Llama, Mistral) | GPT-4, GPT-3.5 | Broader: Phi, Llama, Mistral, GPT-4o |
| **Setup** | Local GPU/CPU | Cloud API | Cloud API |
| **Scalability** | Single machine | Unlimited | Unlimited |
| **Data Privacy** | Local only | Microsoft-hosted | Microsoft-hosted |
| **Tool Calling** | Requires parser | Native support ✓ | Native support ✓ |

---

## Migration Considerations

### ✅ **Advantages of Azure:**
- Professional SLA and support
- Better tool-calling reliability (native OpenAI API support)
- Scales infinitely without GPU constraints
- Can easily switch between models

### ⚠️ **Trade-offs:**
- Requires Azure credentials and subscription
- Network latency (though usually negligible)
- Pay-per-token cost model
- Data goes to Microsoft cloud

### ✅ **No Code Changes Needed For:**
- Agent logic (LangGraph graph structure)
- Tool definitions
- Server.py routing (SSE streaming works the same)
- React UI (completely unchanged)

---

## Quick Start: Switch Today

### Option A: Minimal Change (Keep Everything Else)
Replace only the LLM initialization in agent.py:

```python
# At the top of agent.py
import os
from langchain_openai import AzureChatOpenAI

# Remove the ChatOllama import and initialization
# Add this instead:

llm = AzureChatOpenAI(
    model=os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4"),
    api_version="2024-02-15-preview",
    temperature=0,
    max_tokens=4096
)
```

Then set environment variables and run normally - everything else stays the same!

### Option B: Hybrid Approach
Keep Ollama as fallback:

```python
USE_AZURE = os.environ.get("USE_AZURE", "false").lower() == "true"

if USE_AZURE:
    from langchain_openai import AzureChatOpenAI
    llm = AzureChatOpenAI(model=os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4"))
else:
    from langchain_ollama import ChatOllama
    llm = ChatOllama(model=os.environ.get("OLLAMA_MODEL", "phi4-mini:latest"))
```

Then: `$env:USE_AZURE = "true"` to switch.

---

## Testing the Switch

```powershell
# 1. Set Azure credentials
$env:AZURE_OPENAI_API_KEY = "your-key"
$env:AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
$env:AZURE_DEPLOYMENT_NAME = "gpt-4"

# 2. Start the server (no other changes needed)
cd phi4-agent
python server.py

# 3. Test in React UI - it should work exactly as before
# The trace panel, role cards, all UX features work identically
```

---

## Costs Estimate

### Azure OpenAI (GPT-4):
- Input: ~$0.03 / 1K tokens
- Output: ~$0.06 / 1K tokens
- Example: 100 agent calls with 2K tokens each ≈ $12/month

### Azure AI Foundry (Phi-4, Mistral):
- Input: ~$0.00035 / 1K tokens (much cheaper)
- Output: ~$0.0014 / 1K tokens
- Same workload ≈ $0.50-1.00/month

---

## Documentation Links

- [LangChain Azure OpenAI](https://python.langchain.com/docs/integrations/llms/azure_openai)
- [Azure OpenAI Deployment](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource)
- [Azure AI Foundry Models](https://learn.microsoft.com/en-us/azure/ai-studio/what-is-ai-studio)
