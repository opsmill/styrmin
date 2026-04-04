"""Replacement for Makefile."""

from pathlib import Path

from invoke import Collection, Context, task

from tasks import agent, cluster, dev, graphql_validate
from tasks import format as fmt

from .utils import print_header

MAIN_DIRECTORY_PATH = Path(__file__).parent.parent

ns = Collection()
ns.add_collection(dev)
ns.add_collection(agent)
ns.add_collection(cluster)


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
    """Validate that generated types are up to date."""
    print_header("Validating generated types are up to date...")
    generated_dir = MAIN_DIRECTORY_PATH / "python_sdk" / "src" / "styrmin_sdk" / "graphql" / "_generated"
    context.run("ariadne-codegen", hide=True)
    result = context.run(f"git diff --exit-code {generated_dir}", warn=True, hide=True)
    if result.failed:
        # Restore the committed state so the working tree stays clean
        context.run(f"git checkout -- {generated_dir}", hide=True)
        raise SystemExit("Generated types are out of date. Run 'uv run invoke generate' to update them.")


ns.add_task(local_run)
ns.add_task(test)
ns.add_task(format_all)
ns.add_task(lint_all)
ns.add_task(generate_types)
ns.add_task(generate_validate)
ns.add_task(graphql_validate.validate_graphql)
