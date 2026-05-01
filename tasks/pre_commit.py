from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from invoke.tasks import task

from .utils import MAIN_DIRECTORY_PATH, print_header

if TYPE_CHECKING:
    from invoke.context import Context


_INSTALL_HINT = (
    "prek not found on PATH. Install it and re-run:\n"
    "  brew install j178/prek/prek    # macOS\n"
    "  # or fetch the binary from https://github.com/j178/prek/releases\n"
    "See dev/guides/pre-commit-hooks.md for details."
)


def _ensure_prek() -> None:
    if not shutil.which("prek"):
        raise SystemExit(_INSTALL_HINT)


@task(name="pre-commit-install")
def pre_commit_install(context: Context) -> None:
    """Install git hooks (pre-commit + pre-push) for the project."""
    _ensure_prek()
    print_header("Installing pre-commit hooks via prek")
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run("prek install", pty=True)


@task(name="pre-commit-run")
def pre_commit_run(context: Context) -> None:
    """Run all configured pre-commit hooks against every file in the repo."""
    _ensure_prek()
    print_header("Running pre-commit hooks (--all-files) via prek")
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run("prek run --all-files --show-diff-on-failure", pty=True)
