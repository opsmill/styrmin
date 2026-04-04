"""Task management commands."""

from __future__ import annotations

from cyclopts import App

from styrminctl import client
from styrminctl.output import console, print_table, styrmin_error_handler
from styrminctl.types import TaskId

tasks_app = App(name="tasks", help="View tasks.")


@tasks_app.command(name="list")
async def list_tasks() -> None:
    """List all tasks."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            tasks = await sdk.tasks.list()

    if not tasks:
        console.print("No tasks found.")
        return

    rows = [
        {
            "id": str(t.id),
            "type": t.type_,
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
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.tasks.get(task_id)

    row = {
        "id": str(task.id),
        "type": task.type_,
        "status": task.status,
        "message": task.message or "",
        "deploymentId": str(task.deployment_id) if task.deployment_id else "",
    }
    print_table([row], columns=["id", "type", "status", "message", "deploymentId"], title="Task")
