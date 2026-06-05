# Agentic AI Loan Approval System

An enterprise-style multi-agent loan approval system built with LangGraph,
FastMCP, Claude Sonnet (AWS Bedrock), ChromaDB, FastAPI, and Streamlit.

## Business Goal
Analyze loan applications and classify them as:
- **APPROVED** — meets all policy and risk criteria
- **REJECTED** — fails one or more hard rejection rules
- **REVIEW_REQUIRED** — borderline case requiring human review

## Tech Stack
| Layer | Technology |
|-------|-----------|
| UI | Streamlit |
| Gateway | FastAPI |
| Orchestration | LangGraph |
| Tool Protocol | FastMCP |
| LLM | Claude Sonnet via AWS Bedrock |
| Vector DB | ChromaDB |
| Embeddings | sentence-transformers |
| Config | YAML + python-dotenv |
| Logging | structlog |

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env  # fill in AWS credentials

# 3. Ingest policy docs
python -m rag.ingest

# 4. Start MCP server (terminal 1)
python -m mcp.server

# 5. Start API server (terminal 2)
uvicorn api.main:app --port 8000 --reload

# 6. Start UI (terminal 3)
streamlit run ui/app.py
```

## Agents
| Agent | Role |
|-------|------|
| Applicant Profile Agent | Data validation, employment assessment |
| Financial Risk Agent | DTI, credit scoring, risk bands |
| Policy Knowledge Agent | RAG retrieval from ChromaDB |
| Loan Decision Agent | Final verdict + confidence + explanation |
| Compliance Agent | Audit trail, Case ID, notification |

## Input Fields
Applicant ID, Age, Income, Employment Type, Credit Score,
Loan Amount, Loan Tenure, Existing Liabilities, Location, Timestamp
