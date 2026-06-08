# Weave — Local Setup Guide

---

## Prerequisites

| Tool | Min version | Install |
|------|-------------|---------|
| Python | 3.11+ | [python.org/downloads](https://www.python.org/downloads/) |
| Docker | 24+ | [docs.docker.com/get-docker](https://docs.docker.com/get-docker/) |
| Docker Compose | v2+ | Included with Docker Desktop |
| Git | 2.30+ | [git-scm.com/downloads](https://git-scm.com/downloads) |

---

## Option A — Docker (recommended)

This is the fastest way to get everything running.

1. **Clone the repository**
   ```bash
   git clone https://github.com/KhushneetSingh/Weave.git
   cd Weave
   ```

2. **Copy the environment template**
   ```bash
   cp .env.example .env
   ```

3. **Add your OpenRouter API key**
   ```bash
   # Edit .env and set:
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```

4. **Start all services**
   ```bash
   docker compose up --build
   ```

5. **Wait for healthchecks** — Postgres and Redis must be healthy before the API starts. Docker Compose handles this via `depends_on: condition: service_healthy`.

6. **Run migrations** (first time only)
   ```bash
   docker compose exec api alembic upgrade head
   ```

7. **Verify**
   ```bash
   curl http://localhost:8000/health
   # Expected: {"status": "ok", "version": "0.4.0"}
   ```

---

## Option B — Local (no Docker)

Run each service manually for faster development iteration.

1. **Clone and enter**
   ```bash
   git clone https://github.com/KhushneetSingh/Weave.git
   cd Weave
   ```

2. **Create a virtual environment**
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate   # macOS/Linux
   # or: venv\Scripts\activate  # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set environment variables**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set:
   ```
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5433
   REDIS_URL=redis://localhost:6379/0
   ```

5. **Start Postgres and Redis** (via Docker)
   ```bash
   docker compose up db redis -d
   ```

6. **Run Alembic migrations**
   ```bash
   alembic upgrade head
   ```

7. **Start the API**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

8. **Start the Celery worker** (separate terminal)
   ```bash
   source venv/bin/activate
   celery -A app.worker:celery_app worker --loglevel=info
   ```

9. **Start the Log UI** (optional, separate terminal)
   ```bash
   source venv/bin/activate
   uvicorn log_ui.main:app --host 0.0.0.0 --port 8080 --reload
   ```

---

## 🔑 Getting an OpenRouter API key

1. Go to [openrouter.ai](https://openrouter.ai)
2. Sign up (free tier available)
3. Navigate to **Keys** → **Create key**
4. Copy the key and paste it into `.env` as `OPENROUTER_API_KEY`

> The default models (`llama-3.1-8b-instruct:free` and `mistral-7b-instruct:free`) are free. No credit card required.

---

## ✅ Verifying the setup

Test each endpoint with these curl commands:

**Health check:**
```bash
curl http://localhost:8000/health
# Expected: {"status": "ok", "version": "0.4.0"}
```

**Run a query:**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is RAG?", "max_budget": 4000}' \
  --no-buffer
# Expected: SSE stream with events: job_created, agent_start, token, routing, done
```

**Get job trace** (use a job_id from the query response):
```bash
curl http://localhost:8000/jobs/<job_id>/trace
# Expected: {"job_id": "...", "query": "...", "status": "completed", "events": [...]}
```

**Start eval run:**
```bash
curl -X POST http://localhost:8000/eval/run \
  -H "Content-Type: application/json" \
  -d '{}'
# Expected: {"run_id": "...", "status": "started", "case_count": 15}
```

**Get latest eval results:**
```bash
curl http://localhost:8000/eval/latest
# Expected: {"run_id": "...", "by_category": {...}, "by_dimension": {...}}
```

---

## ❌ Common errors

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `Connection refused on port 5432` | Postgres not running | Run `docker compose up db -d` and wait for healthcheck |
| `Connection refused on port 6379` | Redis not running | Run `docker compose up redis -d` |
| `openai.AuthenticationError` | Missing or invalid `OPENROUTER_API_KEY` | Check `.env` — key must start with `sk-or-` |
| `alembic.util.exc.CommandError: Can't locate revision` | Migrations not run | Run `alembic upgrade head` |
| `ModuleNotFoundError: No module named 'app'` | Virtual environment not activated or wrong working directory | Activate venv and run from project root |
| `asyncpg.InvalidCatalogNameError: database "weave" does not exist` | Postgres not initialized with correct DB name | Ensure `POSTGRES_DB=weave` in `.env` (matches `.env.example` and `config.py` defaults) |
| `celery.exceptions.NotRegistered` | Worker not discovering tasks | Ensure you run celery with `-A app.worker:celery_app` |
