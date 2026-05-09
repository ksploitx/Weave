# Contributing to Weave

Thanks for your interest in contributing! This guide covers everything you need to get started.

---

## 🛠️ Dev setup (no Docker)

For faster iteration, you can run the API locally without Docker.

```bash
# 1. Clone and enter
git clone https://github.com/KhushneetSingh/Weave.git
cd Weave

# 2. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env: add OPENROUTER_API_KEY, set POSTGRES_HOST=localhost

# 5. Start Postgres + Redis (via Docker, or local installs)
docker compose up db redis -d

# 6. Run Alembic migrations
alembic upgrade head

# 7. Start the API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 8. (Optional) Start the Celery worker in a second terminal
celery -A app.worker:celery_app worker --loglevel=info
```

---

## 🌿 Branching

| Branch | Purpose |
|--------|---------|
| `main` | Stable, deployable code |
| `feat/your-feature` | Feature branches — PRs only to `main` |

> Never push directly to `main`. Always open a pull request.

---

## 📝 Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/).

| Prefix | When to use |
|--------|-------------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `chore:` | Tooling, dependencies, CI |
| `test:` | Tests only |

**Examples:**
```
feat: add web_search retry backoff
fix: budget manager not resetting on compression
docs: update ARCHITECTURE.md routing section
chore: bump openai to 1.31.0
test: add adversarial injection test cases
```

---

## 🤖 Adding a new agent

1. **Create `app/agents/your_agent.py`** extending `BaseAgent`
2. **Declare** `agent_id` and `max_budget` as class attributes
3. **Set** `system_prompt` — must include JSON output format instructions
4. **Implement `_build_messages(context)`** — read from `SharedContext`, return OpenAI-style messages list
5. **Implement `_parse_output(parsed, context)`** — convert parsed LLM JSON into `AgentOutput`, write to context
6. **Never call other agents directly** — communication happens only through `SharedContext`
7. **Register the node** in `app/core/orchestrator.py`:
   ```python
   async def your_agent_node(state: GraphState) -> GraphState:
       return await _run_agent(YourAgent(), state)
   
   # In build_graph():
   graph.add_node("your_agent", your_agent_node)
   ```
8. **Add routing rule** to `route()` function in `orchestrator.py`
9. **Add re-export** to `app/agents/__init__.py`

---

## 🔧 Adding a new tool

1. **Create `app/tools/your_tool.py`** extending `BaseTool`
2. **Set** `name`, `timeout_seconds`, and `max_retries` as class attributes
3. **Implement `_execute(input)`** — the core tool logic, return a `ToolResult`
4. **Implement failure handlers:**
   - `on_timeout()` — what to return when the tool times out
   - `on_empty()` — what to return when input is empty
   - `on_malformed(error)` — what to return on parse/execution errors
5. **Optionally override `_modify_input_on_retry(input, result)`** for retry strategies
6. **Register in `app/tools/__init__.py`:**
   ```python
   from app.tools.your_tool import YourTool
   
   TOOL_REGISTRY["your_tool"] = YourTool
   ```
7. **Use in the agent** that needs it by calling `tool.call(input, job_id, agent_id)`

---

## ✅ Pull request checklist

Before submitting a PR, verify:

- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] New code has docstrings with parameter descriptions
- [ ] No hardcoded credentials or API keys in code
- [ ] Alembic migration included if any model changed
- [ ] Commit messages follow conventional commit format
- [ ] README/docs updated if behaviour changed
