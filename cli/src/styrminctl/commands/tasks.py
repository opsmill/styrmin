"""Task management commands."""

from __future__ import annotations

from cyclopts import App
from styrmin_sdk.exceptions import StyrminError

from styrminctl import client
from styrminctl.output import console, print_error, print_table
from styrminctl.types import TaskId

tasks_app = App(name="tasks", help="View tasks.")


@tasks_app.command(name="list")
async def list_tasks() -> None:
    """List all tasks."""
    async with client.get_client() as sdk:
        try:
            tasks = await sdk.tasks.list()
        except StyrminError as e:
            print_error(str(e))
            raise SystemExit(1) from e

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


@tasks_app.command
async def get(task_id: TaskId) -> None:
    """Get a task by ID."""
    async with client.get_client() as sdk:
        try:
            task = await sdk.tasks.get(task_id)
        except StyrminError as e:
            print_error(str(e))
            raise SystemExit(1) from e

    row = {
        "id": str(task.id),
        "type": task.type,
        "status": task.status,
        "message": task.message or "",
        "deploymentId": str(task.deployment_id) if task.deployment_id else "",
    }
    print_table([row], columns=["id", "type", "status", "message", "deploymentId"], title="Task")
