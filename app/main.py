import asyncio
import json
import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Weave",
    description="Multi-agent LLM orchestration system — Phase 2",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request schema ────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    max_budget: int = 4000


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Liveness probe — returns 200 when the API process is running."""
    return {"status": "ok", "version": app.version}


# ── SSE helper ────────────────────────────────────────────────────────────────
def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, default=str)}\n\n"


# ── POST /query  ──────────────────────────────────────────────────────────────
@app.post("/query", tags=["orchestration"])
async def query_endpoint(body: QueryRequest):
    """
    Launch the multi-agent pipeline and stream results via SSE.

    Event types:
        job_created, agent_start, token, tool_call, tool_result,
        routing, budget_update, done, error
    """
    job_id = str(uuid.uuid4())
    start_time = time.perf_counter()

    # ── Create job in DB ──────────────────────────────────────────────
    try:
        from app.database import AsyncSessionLocal
        from app.models.job import Job, JobStatus

        async with AsyncSessionLocal() as session:
            job = Job(id=job_id, query=body.query, status=JobStatus.RUNNING)
            session.add(job)
            await session.commit()
    except Exception as exc:
        logger.error("Failed to create job in DB: %s", exc)

    # ── Event generator ───────────────────────────────────────────────
    async def event_generator():
        event_queue: asyncio.Queue = asyncio.Queue()

        yield _sse_event({"type": "job_created", "job_id": job_id})

        # Run pipeline in background task
        pipeline_task = asyncio.create_task(
            _run_pipeline(body.query, job_id, body.max_budget, event_queue)
        )

        # Stream events from queue until pipeline completes
        while True:
            # Check if pipeline is done
            if pipeline_task.done():
                # Drain remaining events
                while not event_queue.empty():
                    event = event_queue.get_nowait()
                    yield _sse_event(event)
                break

            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                yield _sse_event(event)
            except asyncio.TimeoutError:
                continue

        # Handle pipeline result
        total_ms = (time.perf_counter() - start_time) * 1000
        try:
            ctx = pipeline_task.result()
            total_tokens = sum(
                o.token_count for o in ctx.agent_outputs.values()
            )
            # Update job in DB
            await _update_job_status(job_id, "completed", total_tokens, int(total_ms))

            yield _sse_event({
                "type": "done",
                "job_id": job_id,
                "total_tokens": total_tokens,
                "latency_ms": round(total_ms, 2),
            })
        except Exception as exc:
            await _update_job_status(job_id, "failed", 0, int(total_ms))
            yield _sse_event({
                "type": "error",
                "error_code": type(exc).__name__,
                "message": str(exc),
                "job_id": job_id,
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _run_pipeline(query, job_id, max_budget, event_queue):
    """Run the orchestrator pipeline — called as a background task."""
    from app.core.orchestrator import run_pipeline
    return await run_pipeline(
        query=query,
        job_id=job_id,
        max_budget=max_budget,
        event_queue=event_queue,
    )


async def _update_job_status(
    job_id: str, status: str, total_tokens: int, total_latency_ms: int
) -> None:
    """Update job row in Postgres."""
    try:
        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.database import AsyncSessionLocal
        from app.models.job import Job, JobStatus

        status_enum = JobStatus(status)
        async with AsyncSessionLocal() as session:
            stmt = (
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=status_enum,
                    total_tokens=total_tokens,
                    total_latency_ms=total_latency_ms,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.error("Failed to update job status: %s", exc)


# ── Eval / Meta-agent request schemas ─────────────────────────────────────────

class EvalRunRequest(BaseModel):
    case_ids: list[str] | None = None


class PromptReviewRequest(BaseModel):
    decision: str  # "approve" | "reject"
    reviewer_note: str = ""


class ReRunFailedRequest(BaseModel):
    use_approved_prompts: bool = True


# ── POST /eval/run ────────────────────────────────────────────────────────────

@app.post("/eval/run", tags=["eval"])
async def eval_run(body: EvalRunRequest = EvalRunRequest()):
    """
    Start an evaluation run as a Celery background task.
    Returns immediately with a run_id.
    """
    from app.worker.tasks import run_eval_task

    run_type = "targeted" if body.case_ids else "full"
    case_count = len(body.case_ids) if body.case_ids else 15

    task = run_eval_task.delay(
        run_type=run_type,
        case_ids=body.case_ids,
    )

    return {
        "run_id": task.id,
        "status": "started",
        "case_count": case_count,
    }


# ── GET /eval/latest ──────────────────────────────────────────────────────────

@app.get("/eval/latest", tags=["eval"])
async def eval_latest():
    """Return the latest eval run summary grouped by category + dimension."""
    from app.eval.harness import EvalHarness

    harness = EvalHarness()
    return await harness.get_latest_summary()


# ── POST /prompt-rewrites/{rewrite_id}/review ─────────────────────────────────

@app.post("/prompt-rewrites/{rewrite_id}/review", tags=["eval"])
async def review_prompt_rewrite(rewrite_id: str, body: PromptReviewRequest):
    """
    Approve or reject a pending prompt rewrite.

    If approved:
      - Updates PromptRewriteModel.status to "approved"
      - Patches the target agent's system_prompt in memory
      - Triggers re-eval on previously failed cases via Celery
    """
    from datetime import datetime, timezone

    from sqlalchemy import select, update

    from app.database import AsyncSessionLocal
    from app.models.prompt_rewrite import PromptRewrite as PromptRewriteModel

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PromptRewriteModel).where(
                PromptRewriteModel.id == uuid.UUID(rewrite_id)
            )
        )
        rewrite = result.scalar_one_or_none()

    if not rewrite:
        return {"error": f"Rewrite {rewrite_id} not found."}, 404

    now = datetime.now(timezone.utc)
    re_eval_triggered = False

    if body.decision == "approve":
        # 1. Update DB status
        async with AsyncSessionLocal() as session:
            stmt = (
                update(PromptRewriteModel)
                .where(PromptRewriteModel.id == uuid.UUID(rewrite_id))
                .values(
                    status="approved",
                    reviewer_note=body.reviewer_note,
                    approved_at=now,
                )
            )
            await session.execute(stmt)
            await session.commit()

        # 2. Patch agent's system_prompt in memory
        _patch_agent_prompt(rewrite.target_agent, rewrite.new_prompt)

        # 3. Trigger re-eval on failed cases
        from app.worker.tasks import run_eval_task

        # Find the eval run associated with this rewrite to get failed cases
        run_eval_task.delay(run_type="full")
        re_eval_triggered = True

        logger.info(
            "Prompt rewrite %s approved for agent=%s. Re-eval triggered.",
            rewrite_id, rewrite.target_agent,
        )

    elif body.decision == "reject":
        async with AsyncSessionLocal() as session:
            stmt = (
                update(PromptRewriteModel)
                .where(PromptRewriteModel.id == uuid.UUID(rewrite_id))
                .values(
                    status="rejected",
                    reviewer_note=body.reviewer_note,
                )
            )
            await session.execute(stmt)
            await session.commit()

        logger.info("Prompt rewrite %s rejected.", rewrite_id)

    return {
        "rewrite_id": rewrite_id,
        "decision": body.decision,
        "timestamp": now.isoformat(),
        "re_eval_triggered": re_eval_triggered,
    }


# ── POST /eval/re-run-failed ─────────────────────────────────────────────────

@app.post("/eval/re-run-failed", tags=["eval"])
async def eval_rerun_failed(body: ReRunFailedRequest = ReRunFailedRequest()):
    """
    Re-run evaluation on previously failed cases.
    Optionally uses approved prompt rewrites.
    """
    from sqlalchemy import desc, select

    from app.database import AsyncSessionLocal
    from app.eval.harness import EvalHarness
    from app.models.eval_run import EvalRun

    # Find the latest run
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EvalRun).order_by(desc(EvalRun.timestamp)).limit(1)
        )
        latest = result.scalar_one_or_none()

    if not latest:
        return {"error": "No previous eval runs found."}

    # If use_approved_prompts, apply any approved rewrites first
    if body.use_approved_prompts:
        await _apply_approved_rewrites()

    # Run failed cases via Celery
    from app.worker.tasks import run_eval_task

    task = run_eval_task.delay(
        run_type="targeted",
        previous_run_id=str(latest.id),
    )

    # Count failed cases
    harness = EvalHarness()
    failed_count = 0
    if latest.scores:
        for entry in latest.scores:
            total = harness._compute_total(entry)
            if total < 0.6:
                failed_count += 1

    return {
        "new_run_id": task.id,
        "cases_rerun": failed_count,
        "performance_delta": latest.delta or {},
    }


# ── Helpers for prompt patching ───────────────────────────────────────────────

def _patch_agent_prompt(agent_id: str, new_prompt: str) -> None:
    """Patch an agent's system_prompt in memory (class-level attribute)."""
    from app.agents.compression import CompressionAgent
    from app.agents.critique import CritiqueAgent
    from app.agents.decomposition import DecompositionAgent
    from app.agents.rag import RAGAgent
    from app.agents.synthesis import SynthesisAgent

    agent_map = {
        "decomposition": DecompositionAgent,
        "rag": RAGAgent,
        "critique": CritiqueAgent,
        "synthesis": SynthesisAgent,
        "compression": CompressionAgent,
    }
    cls = agent_map.get(agent_id)
    if cls:
        cls.system_prompt = new_prompt
        logger.info("Patched system_prompt for agent=%s in memory.", agent_id)
    else:
        logger.warning("Unknown agent_id=%s — cannot patch prompt.", agent_id)


async def _apply_approved_rewrites() -> None:
    """Load all approved rewrites from DB and patch agent prompts."""
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.prompt_rewrite import PromptRewrite as PromptRewriteModel

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PromptRewriteModel).where(PromptRewriteModel.status == "approved")
        )
        rewrites = result.scalars().all()

    for rw in rewrites:
        _patch_agent_prompt(rw.target_agent, rw.new_prompt)

    if rewrites:
        logger.info("Applied %d approved prompt rewrite(s).", len(rewrites))
