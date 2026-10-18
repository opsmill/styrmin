"""Replacement for Makefile."""

import fcntl
import struct
import termios
from pathlib import Path
from typing import IO, Any

from invoke import Collection, Context, task
from invoke import runners as _invoke_runners
from invoke import terminals as _invoke_terminals


# ---------------------------------------------------------------------------
# Monkey-patch: invoke 2.2.1 + Python 3.14 stdin buffer overflow
#
# invoke.terminals.bytes_to_read calls
#   fcntl.ioctl(input_, termios.FIONREAD, b"  ")
# with a 2-byte buffer, but FIONREAD writes a 4-byte int. Python ≤3.13
# silently tolerated the overrun; Python 3.14 raises
#   SystemError: buffer overflow
# from the stdin-forwarding thread, which kills any `context.run(..., pty=True)`
# call (e.g. `uv run invoke start`) right after the subprocess exits.
#
# invoke.runners does `from .terminals import bytes_to_read` at import time,
# so we must rebind the name on `invoke.runners` as well — patching
# `invoke.terminals.bytes_to_read` alone leaves the runners module still
# pointing at the original buggy function.
#
# Upstream bug; no fix released yet. Once invoke ships a version with a
# correctly-sized buffer, bump the pin and DELETE this block.
# ---------------------------------------------------------------------------
def _bytes_to_read_patched(input_: IO[Any]) -> int:
    if not _invoke_terminals.WINDOWS and _invoke_terminals.isatty(input_) and _invoke_terminals.has_fileno(input_):
        buf = fcntl.ioctl(input_, termios.FIONREAD, b"\x00\x00\x00\x00")
        return int(struct.unpack("i", buf)[0])
    return 1


_invoke_terminals.bytes_to_read = _bytes_to_read_patched  # ty: ignore[invalid-assignment]
_invoke_runners.bytes_to_read = _bytes_to_read_patched  # ty: ignore[invalid-assignment]

from tasks import agent, cluster, demo, dev, graphql_validate, pre_commit, release  # noqa: E402
from tasks import format as fmt  # noqa: E402

from .utils import print_header  # noqa: E402

MAIN_DIRECTORY_PATH = Path(__file__).parent.parent

ns = Collection()
ns.add_collection(dev)
ns.add_collection(agent)
ns.add_collection(cluster)
ns.add_collection(release)


@task(name="format")
def format_all(context: Context) -> None:
    """Format all code (Python and Markdown)."""
    fmt.format_python(context)
    fmt.format_markdown(context)


@task(name="lint")
def lint_all(context: Context) -> None:
    """Run all linters (Python, Markdown, and YAML)."""
    fmt.lint_ruff(context)
    fmt.lint_ty(context)
    fmt.lint_markdown(context)
    fmt.lint_yaml(context)
    graphql_validate.validate_graphql(context)
    generate_validate(context)


@task
def local_run(context: Context) -> None:
    """Run the FastAPI server locally."""
    print_header("Running the FastAPI server locally...")
    context.run("fastapi dev backend/styrmin_backend/server/app.py", pty=True)


@task
def test(context: Context) -> None:
    """Run the tests."""
    print_header("Running the tests...")

    with context.cd("backend"):
        context.run("pytest tests --ignore=tests/e2e", pty=True)


@task(name="generate")
def generate_types(context: Context) -> None:
    """Generate typed models from GraphQL queries (Python SDK + frontend)."""
    print_header("Generating Python types from GraphQL queries...")
    context.run("ariadne-codegen", pty=True)
    print_header("Generating frontend TypeScript types from GraphQL queries...")
    with context.cd("frontend"):
        context.run("pnpm codegen", pty=True)


@task(name="generate-validate")
def generate_validate(context: Context) -> None:
    """Validate that generated types are up to date (Python SDK + frontend)."""
    print_header("Validating generated types are up to date...")
    sdk_generated = MAIN_DIRECTORY_PATH / "python_sdk" / "src" / "styrmin_sdk" / "graphql" / "_generated"
    frontend_generated = MAIN_DIRECTORY_PATH / "frontend" / "src" / "generated"

    context.run("ariadne-codegen", hide=True)
    sdk_result = context.run(f"git diff --exit-code {sdk_generated}", warn=True, hide=True)
    if sdk_result is not None and sdk_result.failed:
        context.run(f"git checkout -- {sdk_generated}", hide=True)
        raise SystemExit("SDK generated types are out of date. Run 'uv run invoke generate' to update them.")

    with context.cd("frontend"):
        context.run("pnpm codegen", hide=True)
    frontend_result = context.run(f"git diff --exit-code {frontend_generated}", warn=True, hide=True)
    if frontend_result is not None and frontend_result.failed:
        context.run(f"git checkout -- {frontend_generated}", hide=True)
        raise SystemExit("Frontend generated types are out of date. Run 'uv run invoke generate' to update them.")


ns.add_task(local_run)
ns.add_task(test)
ns.add_task(format_all)
ns.add_task(lint_all)
ns.add_task(generate_types)
ns.add_task(generate_validate)
ns.add_task(graphql_validate.validate_graphql)
ns.add_task(pre_commit.pre_commit_install)
ns.add_task(pre_commit.pre_commit_run)
ns.add_task(demo.build, name="build")
ns.add_task(demo.start, name="start")
ns.add_task(demo.stop, name="stop")
ns.add_task(demo.destroy, name="destroy")
ns.add_task(demo.reset, name="reset")
ns.add_task(demo.record, name="record")
