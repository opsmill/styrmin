from invoke.collection import Collection
from invoke.context import Context
from invoke.tasks import task

from .utils import BACKEND_DIRECTORY, MAIN_DIRECTORY_PATH

ns = Collection()


@task
def format_python(context: Context) -> None:
    """Run RUFF to format all Python files."""

    exec_cmds = ["ruff format .", "ruff check . --fix"]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            context.run(cmd, pty=True)


@task
def format_markdown(context: Context) -> None:
    """Format markdown files with rumdl."""
    print(" - Formatting markdown files with rumdl")
    exec_cmd = "rumdl fmt ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_mypy(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with mypy")
    exec_cmd = f"mypy --show-error-codes {BACKEND_DIRECTORY}"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_ruff(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with ruff")
    exec_cmd = "ruff check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_ty(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with ty")
    exec_cmd = "ty check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_markdown(context: Context) -> None:
    """Lint markdown files with rumdl."""
    print(" - Check markdown files with rumdl")
    exec_cmd = "rumdl check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_yaml(context: Context) -> None:
    """Run yamllint to check all YAML files."""
    print(" - Check YAML files with yamllint")
    exec_cmd = "yamllint ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


ns.add_task(format_python)
ns.add_task(format_markdown)
ns.add_task(lint_mypy)
ns.add_task(lint_ruff)
ns.add_task(lint_markdown)
ns.add_task(lint_yaml)
