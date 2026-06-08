# Agentic AI Loan Approval System — Claude Code Reference

## Project Overview
Enterprise-style agentic loan approval system. Classifies loan applications as
APPROVED, REJECTED, or REVIEW_REQUIRED using a multi-agent LangGraph pipeline
backed by Claude Sonnet 4.6 on AWS Bedrock.

## LLM Runtime Notes
- Default model target: `anthropic.claude-sonnet-4-6` (configured in `config/settings.py`).
- Agent runtime path: Anthropic SDK `AnthropicBedrock` client in `agents/base_agent.py`.
- Fallback path: boto3 Bedrock invoke_model remains enabled when SDK client init is unavailable.

## Reviewer Verification Steps
1. Check configured model target:
```bash
rg "anthropic\.claude-sonnet-4-6" config/settings.py
```

2. Check SDK invocation path:
```bash
rg "AnthropicBedrock|messages\.create" agents/base_agent.py
```

3. Check fallback path:
```bash
rg "invoke_model|anthropic_sdk_init_failed_fallback_to_boto3" agents/base_agent.py
```

4. Run one request through the system and verify logs include:
- `anthropic_sdk_enabled_for_agent_calls`, or
- `anthropic_sdk_init_failed_fallback_to_boto3`

## Approval Workflow Command

Use this command for automated compliance verification:

```bash
pytest -q tests/unit/test_llm_runtime_compliance.py
```

The command passes only when all three checks are true:
1. Sonnet 4.6 model target is configured.
2. Anthropic SDK invocation path exists.
3. boto3 fallback path exists.

## Architecture Summary
```
Streamlit UI (8501) → FastAPI Gateway (8000) → LangGraph Orchestrator
→ FastMCP Server (8080) → Agents → Claude Sonnet (Bedrock) → ChromaDB
```

## How to Run

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
cp .env.example .env
# Edit .env with real AWS credentials
```

### 3. Ingest policy documents into ChromaDB
```bash
python -m rag.ingest
```

### 4. Start FastMCP server
```bash
python -m mcp.server
```

### 5. Start FastAPI gateway
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Start Streamlit UI
```bash
streamlit run ui/app.py --server.port 8501
```

### 7. Run tests
```bash
pytest tests/ -v --cov=.
```

## Key Conventions
- All agents extend `agents/base_agent.py:BaseAgent`
- All MCP tools live in `mcp/tools/` — one file per agent
- Business rules live only in `config/rules.yaml` — never hardcode thresholds
- Prompt templates live only in `prompts/` — never hardcode prompts in Python
- All modules use `utils/logger.py:get_logger(__name__)` for logging
- Audit records written only through `utils/audit.py:write_audit_record()`

## Project Structure
```
loan_approval_system/
├── api/          FastAPI gateway
├── orchestrator/ LangGraph graph + state
├── agents/       Claude Sonnet agents (5)
├── mcp/          FastMCP server + tools (5)
├── rag/          ChromaDB ingestion + retrieval
├── knowledge_base/ Policy documents (plain text)
├── prompts/      Agent prompt templates (plain text)
├── config/       Business rules YAML + settings
├── ui/           Streamlit multi-page app
├── utils/        Logger + audit writer
├── tests/        Unit + integration tests
└── audit/logs/   Runtime audit records
```
