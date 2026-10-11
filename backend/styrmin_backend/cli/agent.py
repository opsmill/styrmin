"""Agent management commands for Styrmin CLI.

Provides the `styrmin agent start` command that runs the combined
kopf operator and Prefect worker in a single async process, and
`styrmin agent apply-crds`, which the agent chart's hook runs.
"""

import asyncio
import logging
import sys
from pathlib import Path

from cyclopts import App
from rich.console import Console

from styrmin_backend import config

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

    # The operator's handler modules read settings at import: load and validate them first.
    settings = config.SETTINGS.initialize_and_exit()

    from styrmin_backend.entrypoint.combined import main

    asyncio.run(
        main(settings=settings, work_pool_name=work_pool, clusterwide=clusterwide)
    )


@agent_app.command(name="apply-crds")
def apply_crds(directory: Path) -> None:
    """Apply the CustomResourceDefinitions in the YAML files of a directory.

    Uses server-side apply. A CRD that would drop a version the cluster stored objects in is
    deleted and created again when it has no objects, and fails the command otherwise.

    Args:
        directory: Directory holding one or more CRD YAML files.
    """
    from styrmin_backend.operator.crd.install import (
        CrdApplyError,
        apply_crds as apply_crd_list,
        load_crd_files,
    )
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    async def run() -> None:
        crds = load_crd_files(directory)
        async with get_kubernetes_client() as client:
            for result in await apply_crd_list(client, crds):
                console.print(f"{result.name}: {result.action.value}")

    try:
        asyncio.run(run())
    except CrdApplyError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)
