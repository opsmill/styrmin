from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from invoke.tasks import task

from .utils import MAIN_DIRECTORY_PATH, print_header

if TYPE_CHECKING:
    from invoke.context import Context


_INSTALL_HINT = (
    "No pre-commit runner found. Install one and re-run:\n"
    "  - prek (recommended, fast):   https://github.com/j178/prek\n"
    "  - pre-commit (Python):        run `uv sync` (it's already in [dependency-groups].dev)\n"
    "See dev/guides/pre-commit-hooks.md for details."
)


def _resolve_runner() -> str:
    if shutil.which("prek"):
        return "prek"
    if shutil.which("pre-commit"):
        return "pre-commit"
    if shutil.which("uv"):
        return "uv run pre-commit"
    raise SystemExit(_INSTALL_HINT)


@task(name="pre-commit-install")
def pre_commit_install(context: Context) -> None:
    """Install git hooks (pre-commit + pre-push) for the project."""
    runner = _resolve_runner()
    print_header(f"Installing pre-commit hooks via `{runner}`")
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(f"{runner} install", pty=True)


@task(name="pre-commit-run")
def pre_commit_run(context: Context) -> None:
    """Run all configured pre-commit hooks against every file in the repo."""
    runner = _resolve_runner()
    print_header(f"Running pre-commit hooks (--all-files) via `{runner}`")
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(f"{runner} run --all-files --show-diff-on-failure", pty=True)
