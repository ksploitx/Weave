"""
Celery tasks for evaluation and meta-agent workflows.

These tasks run asynchronously via the Celery worker and are triggered
by the API endpoints in app.main.
"""

from __future__ import annotations

import asyncio
import logging

from app.worker import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If there's already a running loop (unlikely in worker),
            # create a new one in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(name="app.worker.tasks.run_eval_task", bind=True)
def run_eval_task(
    self,
    run_type: str = "full",
    previous_run_id: str | None = None,
    case_ids: list[str] | None = None,
) -> dict:
    """
    Run the evaluation harness as a background Celery task.

    Parameters
    ----------
    run_type : str
        "full" or "targeted".
    previous_run_id : str | None
        If provided, re-run only failed cases from this run.
    case_ids : list[str] | None
        If provided, run only these specific case IDs.

    Returns
    -------
    dict
        {"run_id": str, "status": "completed" | "failed"}
    """
    logger.info(
        "Eval task started: run_type=%s previous_run_id=%s case_ids=%s",
        run_type, previous_run_id, case_ids,
    )

    async def _execute():
        from app.eval.harness import EvalHarness

        harness = EvalHarness()

        if previous_run_id:
            run_id = await harness.run_failed(previous_run_id)
        else:
            run_id = await harness.run_all(run_type=run_type, case_ids=case_ids)

        return run_id

    try:
        run_id = _run_async(_execute())

        # Automatically trigger meta-agent analysis after eval
        run_meta_agent_task.delay(run_id)

        return {"run_id": run_id, "status": "completed"}
    except Exception as exc:
        logger.error("Eval task failed: %s", exc, exc_info=True)
        return {"run_id": None, "status": "failed", "error": str(exc)}


@celery_app.task(name="app.worker.tasks.run_meta_agent_task", bind=True)
def run_meta_agent_task(self, run_id: str) -> dict:
    """
    Run the meta-agent to analyse failures and propose prompt rewrites.

    Triggered automatically after each eval run completes.

    Parameters
    ----------
    run_id : str
        The eval run ID to analyse.

    Returns
    -------
    dict
        {"rewrite_id": str | None, "status": str}
    """
    logger.info("Meta-agent task started for run_id=%s", run_id)

    async def _execute():
        from app.agents.meta import MetaAgent

        meta = MetaAgent()
        rewrite = await meta.analyze_failures(run_id)
        return rewrite

    try:
        rewrite = _run_async(_execute())
        if rewrite:
            return {
                "rewrite_id": rewrite.id,
                "target_agent": rewrite.target_agent,
                "target_dimension": rewrite.target_dimension,
                "status": "proposed",
            }
        return {"rewrite_id": None, "status": "no_rewrite_needed"}
    except Exception as exc:
        logger.error("Meta-agent task failed: %s", exc, exc_info=True)
        return {"rewrite_id": None, "status": "failed", "error": str(exc)}
