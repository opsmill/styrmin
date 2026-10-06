"""Task management commands."""

from __future__ import annotations

from cyclopts import App
from rich.markup import escape
from styrmin_sdk.models import StepStatus, TaskStep

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


def _format_duration(total_seconds: float) -> str:
    """Format seconds as ``45s``, ``1m 05s`` or ``1h 02m``, like the deployment page."""
    if total_seconds < 1:
        return "<1s"
    seconds = int(total_seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _step_duration(step: TaskStep) -> str:
    if step.status == StepStatus.RUNNING:
        return "running"
    return _format_duration(step.duration_seconds) if step.duration_seconds is not None else ""


def _step_error(step: TaskStep) -> str:
    """The newest error, FluxCD's detail and the last output line, one per line."""
    lines = [line for line in (step.output or "").splitlines() if line.strip()]
    parts = [step.error, step.detail, f"output: {lines[-1]}" if step.has_output and lines else None]
    # Errors and output are free text: keep "[...]" from being read as Rich markup.
    return escape("\n".join(part for part in parts if part))


@tasks_app.command
async def get(task_id: TaskId) -> None:
    """Get a task by ID, with its steps and the tasks its hook steps started."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.tasks.get(task_id)

    row = {
        "id": str(task.id),
        "type": task.type_,
        "status": task.status,
        "result": task.result.value,
        "message": task.message or "",
        "deploymentId": str(task.deployment_id) if task.deployment_id else "",
    }
    print_table([row], columns=["id", "type", "status", "result", "message", "deploymentId"], title="Task")

    if task.steps:
        steps = [
            {
                "step": step.name,
                "status": step.status.value,
                "duration": _step_duration(step),
                "attempts": step.attempt_count,
                "error": _step_error(step),
            }
            for step in task.steps
        ]
        print_table(steps, columns=["step", "status", "duration", "attempts", "error"], title="Steps")
    else:
        console.print("No steps recorded for this task.")

    if task.started_tasks:
        started = [
            {"id": str(started.id), "type": started.type_, "result": started.result.value}
            for started in task.started_tasks
        ]
        print_table(started, columns=["id", "type", "result"], title="Started tasks")
