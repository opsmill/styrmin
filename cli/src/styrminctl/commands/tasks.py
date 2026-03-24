"""Task management commands."""

from __future__ import annotations

import typer
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError

from styrminctl.async_typer import AsyncTyper as Typer
from styrminctl.config import SETTINGS
from styrminctl.output import console, print_error, print_table

app = Typer()


def _get_client() -> StyrminClient:
    return StyrminClient(
        server_address=SETTINGS.server_address,
        timeout=SETTINGS.timeout,
        headers=SETTINGS.additional_headers,
    )


@app.command(name="list")
async def list_tasks() -> None:
    """List all tasks."""
    async with _get_client() as client:
        try:
            tasks = await client.tasks.list()
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    if not tasks:
        console.print("No tasks found.")
        return

    rows = [
        {
            "id": str(t.id),
            "type": t.type,
            "status": t.status,
            "message": t.message or "",
            "deploymentId": str(t.deployment_id) if t.deployment_id else "",
        }
        for t in tasks
    ]
    print_table(rows, columns=["id", "type", "status", "message", "deploymentId"], title="Tasks")


@app.command()
async def get(
    task_id: str = typer.Argument(..., help="UUID of the task"),
) -> None:
    """Get a task by ID."""
    async with _get_client() as client:
        try:
            task = await client.tasks.get(task_id)
        except StyrminError as e:
            print_error(str(e))
            raise typer.Exit(code=1) from e

    row = {
        "id": str(task.id),
        "type": task.type,
        "status": task.status,
        "message": task.message or "",
        "deploymentId": str(task.deployment_id) if task.deployment_id else "",
    }
    print_table([row], columns=["id", "type", "status", "message", "deploymentId"], title="Task")
