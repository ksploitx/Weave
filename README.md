<h1 align="center">Weave</h1>
<p align="center">Real-time multi-agent LLM orchestration system with self-improving eval loop</p>

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white) ![LangGraph](https://img.shields.io/badge/LangGraph-0.4-1C3C3C?logo=langchain&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white) ![OpenRouter](https://img.shields.io/badge/OpenRouter-API-6366F1) ![License](https://img.shields.io/badge/License-MIT-green)

---

## 🔍 What is Weave

Weave is a multi-agent orchestration system that decomposes complex queries across specialised AI agents, coordinates them via a LangGraph state machine with dynamic routing and token-budget enforcement, and streams every intermediate step to the client over SSE. It continuously improves its own agent prompts through a 6-dimensional evaluation harness that scores 15 test cases, identifies weak dimensions, and proposes targeted prompt rewrites — all under human-in-the-loop review.

---

## 🏗️ Architecture

```
                          +---------------------------+
                          |    FastAPI  (port 8000)    |
  +--------+              |  POST /query (SSE stream)  |            +---------+
  | Client | ----------> |  GET  /jobs/{id}/trace      | ---------> | Celery  |
  +--------+              |  POST /eval/run             |            | Worker  |
                          |  GET  /eval/latest          |            +---------+
                          |  POST /prompt-rewrites/review|               |
                          |  POST /eval/re-run-failed   |               |
                          +-------------+---------------+               |
                                        |                               |
                                        v                               |
                          +----------------------------+                |
                          |   LangGraph Orchestrator    |                |
                          |  (StateGraph + dynamic      |                |
                          |   routing function)         |                |
                          +--+-----+-----+-----+----+--+                |
                             |     |     |     |    |                   |
              +--------------+     |     |     |    +----------+       |
              v                    v     |     v               v       |
       +--------------+  +------+ |  +----------+  +-------------+    |
       | Decomposition|  | RAG  | |  | Critique |  | Compression |    |
       | budget: 1200 |  | 2000 | |  |   1500   |  |    800      |    |
       +--------------+  +--+---+ |  +----------+  +-------------+    |
                            |     |                                    |
                         +--+--+  |                                    |
                         |FAISS|  v                                    |
                         +-----+  +-----------+                        |
                                  | Synthesis |                        |
                                  |   1500    |                        |
                                  +-----------+                        |
                                        |                              |
         +------------------------------v----------------------------+ |
         |                   SharedContext (in-memory)                | |
         |  sub_tasks | agent_outputs | contradictions | provenance  | |
         +------+----------+----------+----------+----------+-------+ |
                |          |          |          |          |           |
                v          v          v          v          v           v
          +----------+ +-------+ +-----------+ +-------+ +----------+
          |PostgreSQL| | Redis | |OpenRouter | | Tools | | Log UI   |
          | 5 tables | |Celery | |  (LLM)    | |  x4   | | port 8080|
          +----------+ +-------+ +-----------+ +-------+ +----------+
```

---

## 🤖 Agents

| Agent | Budget | Role | Writes to context |
|-------|-------:|------|-------------------|
| **Decomposition** | 1 200 tok | Breaks query into a SubTask dependency DAG | `sub_tasks[]` |
| **RAG** | 2 000 tok | Multi-hop FAISS retrieval (15 docs, 2-hop, min 4 chunks) | `agent_outputs["rag"]`, `citations[]` |
| **Critique** | 1 500 tok | Per-claim confidence scoring, span-level flagging | `contradictions[]`, `flagged_spans[]` |
| **Synthesis** | 1 500 tok | Resolves contradictions, builds provenance map | `provenance_map`, final answer |
| **Compression** | 800 tok | Triggered by NeedCompressionError — summarises context | Compressed `agent_outputs` content |
| **Meta** | 1 000 tok | Analyses eval failures, proposes prompt rewrites | `PromptRewrite` (pending in DB) |

---

## 🔧 Tools

| Tool | Failure modes | Max retries |
|------|---------------|:-----------:|
| **web_search** | `timeout`, `empty`, `parse_error` | 2 |
| **sql_lookup** | `timeout`, `empty`, `parse_error` (blocked DDL/DML) | 2 |
| **code_sandbox** | `timeout`, `error` (blocked imports: os, sys, subprocess, shutil, pathlib) | 2 |
| **self_reflection** | `timeout`, `empty`, `error` | 2 |

---

## 🚀 Quick start

```bash
git clone https://github.com/KhushneetSingh/Weave.git
cd Weave
cp .env.example .env
# add your OPENROUTER_API_KEY to .env
docker compose up
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/query` | Run the multi-agent pipeline. Returns SSE stream. |
| `GET` | `/jobs/{job_id}/trace` | Ordered event trace (agent + tool logs) for a job. |
| `POST` | `/eval/run` | Start a 15-case evaluation run via Celery. |
| `GET` | `/eval/latest` | Latest eval results grouped by category + dimension. |
| `POST` | `/prompt-rewrites/{id}/review` | Approve or reject a pending prompt rewrite. |
| `POST` | `/eval/re-run-failed` | Re-run only previously failed eval cases. |
| `GET` | `/health` | Liveness probe — returns `{"status": "ok"}`. |

---

## 🌍 Environment variables

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `OPENROUTER_API_KEY` | **Yes** | — | Your OpenRouter API key |
| `OPENROUTER_MODEL` | No | `meta-llama/llama-3.1-8b-instruct:free` | Primary LLM model |
| `OPENROUTER_FALLBACK_MODEL` | No | `mistralai/mistral-7b-instruct:free` | Fallback if primary fails |
| `POSTGRES_USER` | No | `weave` | Postgres username |
| `POSTGRES_PASSWORD` | No | `weave` | Postgres password |
| `POSTGRES_DB` | No | `weave` | Postgres database name |
| `POSTGRES_HOST` | No | `db` | Postgres host (Docker service name) |
| `POSTGRES_PORT` | No | `5432` | Postgres port |
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis URL for Celery broker |
| `MAX_CONTEXT_TOKENS` | No | `4000` | Max token budget per query |
| `LOG_LEVEL` | No | `INFO` | Logging level |

---

## 📊 Eval pipeline

The evaluation harness runs 15 test cases through the full orchestration pipeline and scores each across 6 dimensions.

| Category | Cases | What's tested |
|----------|:-----:|---------------|
| **Baseline** | 5 | Known correct answers — factual recall |
| **Ambiguous** | 5 | Underspecified inputs — tests decomposition quality |
| **Adversarial** | 5 | Prompt injections, wrong premises, forced contradictions |

**6 scoring dimensions:**

- 📝 **answer_correctness** — does the final output match the expected answer?
- 📎 **citation_accuracy** — are RAG citations valid and grounded in retrieved chunks?
- ⚔️ **contradiction_resolution** — were flagged contradictions resolved by synthesis?
- ⚡ **tool_efficiency** — were tool calls appropriate for the case type?
- 💰 **budget_compliance** — did agents stay within token budget?
- 🤝 **critique_agreement** — did synthesis honour critique feedback?

---

## 🔄 Self-improving loop

1. `POST /eval/run` → runs all 15 cases through the pipeline
2. Each case is scored across 6 dimensions and stored as an `EvalRun` in Postgres
3. **Meta-agent** reads failures → finds the worst dimension → identifies the responsible agent
4. Meta-agent calls the LLM to propose a `PromptRewrite` with unified diff + justification
5. Human reviews → `POST /prompt-rewrites/{id}/review` with `approve` or `reject`
6. If approved → agent's `system_prompt` is patched in memory → targeted re-eval on failed cases only
7. Delta stored in DB for tracking improvement over time

---

## ⚠️ Known limitations

- **OpenRouter free-tier models** (Llama 3.1 8B) are significantly weaker than GPT-4 — citation quality and adversarial robustness suffer
- **FAISS index is in-memory only** — restarts lose the index; no persistence to disk or pgvector
- **Code sandbox is NOT truly isolated** — runs `subprocess.run(["python3", "-c", code])` with no container, no seccomp, no gVisor
- **Eval scoring is heuristic** for ambiguous/adversarial cases — keyword matching, not ground-truth comparison
- **Meta-agent prompt rewrites are LLM-generated** — plausible but not guaranteed to improve scores
- **No authentication on any endpoint** — all routes are publicly accessible
- **No rate limiting** on the API — a flood of `/query` requests will exhaust LLM budget

---

## 🔮 What's next

- 🔀 Replace FAISS with **pgvector** for persistent vector storage across restarts
- 🔒 Add a proper **code sandbox** via gVisor or Firecracker microVMs
- 🖥️ Build a **web UI** for reviewing prompt rewrites and browsing eval results
- 🛡️ Add a **prompt injection detection** layer before the orchestrator
- 📈 Implement **weighted dimension scoring** with configurable weights per use case

---

## 📁 Project structure

```
Weave/
├── app/
│   ├── __init__.py
│   ├── config.py                # Settings from env (pydantic-settings)
│   ├── database.py              # SQLAlchemy async engine + session + Base
│   ├── main.py                  # FastAPI app — all endpoints + error handling
│   ├── agents/
│   │   ├── __init__.py          # Re-exports all agents
│   │   ├── base.py              # BaseAgent ABC — budget, LLM, logging
│   │   ├── decomposition.py     # Query → SubTask DAG
│   │   ├── rag.py               # Multi-hop FAISS retrieval + citations
│   │   ├── critique.py          # Per-claim confidence + span flagging
│   │   ├── synthesis.py         # Contradiction resolution + provenance
│   │   ├── compression.py       # Context compression on budget overflow
│   │   └── meta.py              # Eval failure analysis → prompt rewrites
│   ├── core/
│   │   ├── __init__.py          # Re-exports BudgetManager
│   │   ├── budget_manager.py    # Token budget enforcement
│   │   ├── llm.py               # OpenRouter async client with fallback
│   │   ├── logger.py            # structlog JSON logging + DB persistence
│   │   └── orchestrator.py      # LangGraph StateGraph with dynamic routing
│   ├── eval/
│   │   ├── __init__.py
│   │   ├── harness.py           # Runs test cases through pipeline + scores
│   │   ├── scorer.py            # 6-dimension hand-rolled scorer
│   │   └── test_cases.py        # 15 eval cases (baseline/ambiguous/adversarial)
│   ├── models/
│   │   ├── __init__.py          # Re-exports all ORM models for Alembic
│   │   ├── job.py               # Job ORM model
│   │   ├── agent_log.py         # AgentLog ORM model
│   │   ├── tool_log.py          # ToolLog ORM model
│   │   ├── eval_run.py          # EvalRun ORM model
│   │   └── prompt_rewrite.py    # PromptRewrite ORM model
│   ├── schemas/
│   │   ├── __init__.py          # Re-exports all Pydantic schemas
│   │   ├── context.py           # SharedContext, AgentOutput, SubTask, etc.
│   │   ├── eval.py              # EvalScore, ScoredDimension, PromptRewrite
│   │   └── tools.py             # ToolResult schema
│   ├── tools/
│   │   ├── __init__.py          # TOOL_REGISTRY + re-exports
│   │   ├── base.py              # BaseTool ABC — timeout, retry, logging
│   │   ├── web_search.py        # Simulated web search (fake results)
│   │   ├── sql_lookup.py        # NL → SQL via LLM → asyncpg execution
│   │   ├── code_sandbox.py      # Python subprocess sandbox
│   │   └── self_reflection.py   # Contradiction detection via LLM
│   └── worker/
│       ├── __init__.py          # Celery app configuration
│       └── tasks.py             # Background tasks (eval, meta-agent)
├── alembic/
│   ├── env.py                   # Async Alembic configuration
│   ├── script.py.mako           # Migration template
│   └── versions/
│       ├── 0001_initial.py      # Creates 5 core tables
│       └── 0002_seed_products_orders.py  # products + orders for sql_lookup
├── log_ui/
│   ├── __init__.py
│   └── main.py                  # Standalone FastAPI log viewer (port 8080)
├── tests/
│   ├── __init__.py
│   └── test_budget_manager.py   # 10 tests for ContextBudgetManager
├── archon_viz.py                # Terminal architecture visualizer (rich + networkx)
├── docker-compose.yml           # 5 services: db, redis, api, worker, log_ui
├── Dockerfile                   # Python 3.11-slim
├── requirements.txt
├── alembic.ini
├── pytest.ini
├── .env.example
└── .gitignore
```

---

*Built with AI assistance. See [AI_COLLABORATION.md](./AI_COLLABORATION.md) for full attestation.*
