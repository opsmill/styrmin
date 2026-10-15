"""Combined kopf operator + Prefect worker entrypoint.

Runs both the kopf operator and a Prefect worker in a single async
event loop using asyncio.gather(). Kopf owns signal handling; a
@kopf.on.cleanup handler bridges shutdown to the Prefect worker via
a shared asyncio.Event.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

import anyio
import kopf
from prefect.settings import PREFECT_WORKER_QUERY_SECONDS
from prefect.workers.base import critical_service_loop
from prefect.workers.process import ProcessWorker

# Import handler modules so kopf registers the decorated handlers
import styrmin_backend.operator.handlers.helmrelease  # noqa: F401
import styrmin_backend.operator.handlers.styrmin_deployment  # noqa: F401
import styrmin_backend.operator.handlers.utility_resources  # noqa: F401
import styrmin_backend.operator.janitor  # noqa: F401
from styrmin_backend.agent.status.reporter import run_status_reporter
from styrmin_backend import config

logger = logging.getLogger(__name__)

# Shared shutdown signal: set by kopf cleanup, observed by Prefect worker
_shutdown = asyncio.Event()

#: How long kopf waits for a stopped timer to end its current run before it keeps the finalizer.
TIMER_EXIT_TIMEOUT_SECONDS = 5.0


# --- Kopf lifecycle handlers ---


@kopf.on.startup()
async def on_startup(settings: kopf.OperatorSettings, **_: Any) -> None:
    """Configure kopf operator settings on startup."""
    operator = config.SETTINGS.operator
    settings.peering.name = operator.peering_name
    settings.peering.mandatory = True
    settings.peering.priority = operator.peering_priority
    # Use a shorter, K8s-valid prefix for handler state annotations
    settings.persistence.finalizer = "styrmin.io/kopf-finalizer"
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage(
        prefix="styrmin.io",
    )
    # Without it, a CR deleted during a timer run waits for another event to lose
    # its finalizer, and its namespace can stay Terminating (#446, #461).
    settings.background.instant_exit_timeout = TIMER_EXIT_TIMEOUT_SECONDS
    logger.info(
        "Kopf operator starting with peering=%s priority=%d",
        operator.peering_name,
        operator.peering_priority,
    )


@kopf.on.cleanup()
async def on_cleanup(**_: Any) -> None:
    """Signal the Prefect worker to stop when kopf shuts down."""
    logger.info("Kopf cleanup: signaling Prefect worker to stop")
    _shutdown.set()
    # Brief delay to allow Prefect worker to finish current work
    await asyncio.sleep(2)


# --- Prefect worker ---


async def _worker_loops(worker: ProcessWorker) -> None:
    """Run Prefect worker polling and heartbeat loops."""
    async with anyio.create_task_group() as tg:
        tg.start_soon(
            partial(
                critical_service_loop,
                workload=worker.get_and_submit_flow_runs,
                interval=PREFECT_WORKER_QUERY_SECONDS.value(),
                jitter_range=0.3,
                backoff=4,
            )
        )
        tg.start_soon(
            partial(
                critical_service_loop,
                workload=worker.sync_with_backend,
                interval=worker.heartbeat_interval_seconds,
                jitter_range=0.3,
                backoff=4,
            )
        )


async def run_prefect_worker(
    work_pool_name: str, max_retries: int = 10, retry_delay: float = 5.0
) -> None:
    """Run the Prefect worker until shutdown is signaled.

    Retries on connection errors to handle the case where the Prefect server
    is not yet available at startup (e.g., DNS not resolved, server starting).
    """
    for attempt in range(1, max_retries + 1):
        if _shutdown.is_set():
            return
        try:
            worker = ProcessWorker(work_pool_name=work_pool_name)
            async with worker:
                logger.info(
                    "Prefect worker '%s' started for pool '%s'",
                    worker.name,
                    work_pool_name,
                )
                worker_task = asyncio.create_task(
                    _worker_loops(worker), name="prefect-loops"
                )
                shutdown_task = asyncio.create_task(
                    _shutdown.wait(), name="prefect-shutdown-wait"
                )

                done, pending = await asyncio.wait(
                    [worker_task, shutdown_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError, Exception:
                        pass
                logger.info("Prefect worker '%s' stopped", worker.name)
                return
        except asyncio.CancelledError:
            logger.info("Prefect worker cancelled")
            return
        except Exception:
            if attempt < max_retries:
                logger.warning(
                    "Prefect worker failed to start (attempt %d/%d), retrying in %.0fs",
                    attempt,
                    max_retries,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.exception(
                    "Prefect worker failed to start after %d attempts", max_retries
                )
                raise


# --- Main entrypoint ---


async def main(
    settings: config.Settings,
    work_pool_name: str = "styrmin-work-pool",
    clusterwide: bool = True,
) -> None:
    """Run both kopf operator and Prefect worker concurrently."""
    logger.info(
        "Starting combined operator + Prefect worker (pool=%s, clusterwide=%s)",
        work_pool_name,
        clusterwide,
    )
    await asyncio.gather(
        kopf.operator(clusterwide=clusterwide),
        run_prefect_worker(work_pool_name),
        run_status_reporter(
            shutdown_event=_shutdown,
            graphql_url=settings.url.graphql,
            interval=settings.agent.status_poll_interval,
        ),
    )
