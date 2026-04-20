"""Agent management commands for Styrmin CLI.

Provides the `styrmin agent start` command that runs the combined
kopf operator and Prefect worker in a single async process.
"""

import asyncio
import logging

from cyclopts import App
from rich.console import Console

agent_app = App(name="agent", help="Agent and operator management commands.")
console = Console()


@agent_app.command
def start(
    work_pool: str = "styrmin-work-pool",
    clusterwide: bool = True,
) -> None:
    """Start the combined Kubernetes operator and Prefect worker.

    Runs both the kopf-based operator (for utility resource reconciliation)
    and the Prefect worker (for deployment orchestration) in a single async
    process.

    Args:
        work_pool: Prefect work pool name.
        clusterwide: Watch resources across all namespaces. Set to False for
            namespace-scoped operation.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    console.print(
        f"[bold green]Starting Styrmin agent[/bold green] "
        f"(pool={work_pool}, clusterwide={clusterwide})"
    )

    from styrmin_backend.entrypoint.combined import main

    asyncio.run(main(work_pool_name=work_pool, clusterwide=clusterwide))
