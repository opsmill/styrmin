"""Validate .graphql operation files against the project schema."""

from __future__ import annotations

import sys
from pathlib import Path

from graphql import GraphQLError, build_schema, parse, validate
from invoke import Context, task

from .utils import MAIN_DIRECTORY_PATH, print_header

SCHEMA_FILE = MAIN_DIRECTORY_PATH / "schema.graphql"

EXCLUDE_DIRS = {".venv", "node_modules", "specs"}


def _find_graphql_files() -> list[Path]:
    """Discover all .graphql operation files, excluding non-operation locations."""
    files: list[Path] = []
    for filepath in sorted(MAIN_DIRECTORY_PATH.rglob("*.graphql")):
        # Skip the schema definition itself
        if filepath == SCHEMA_FILE:
            continue
        # Skip excluded directory trees
        relative = filepath.relative_to(MAIN_DIRECTORY_PATH)
        if any(part in EXCLUDE_DIRS for part in relative.parts):
            continue
        files.append(filepath)
    return files


@task(name="validate-graphql")
def validate_graphql(context: Context) -> None:  # noqa: ARG001
    """Validate all .graphql files against the project schema."""
    print_header("Validating GraphQL operations against schema...")

    schema_text = SCHEMA_FILE.read_text()
    schema = build_schema(schema_text)

    graphql_files = _find_graphql_files()

    if not graphql_files:
        print("No .graphql files found to validate.")
        return

    failed_files: list[str] = []
    for filepath in graphql_files:
        relative = filepath.relative_to(MAIN_DIRECTORY_PATH)
        try:
            document = parse(filepath.read_text())
        except GraphQLError as exc:
            print(f"  FAIL  {relative}: Parse error: {exc}")
            failed_files.append(str(relative))
            continue

        validation_errors = validate(schema, document)
        if validation_errors:
            for error in validation_errors:
                print(f"  FAIL  {relative}: {error.message}")
            failed_files.append(str(relative))
        else:
            print(f"  OK    {relative}")

    passed = len(graphql_files) - len(failed_files)
    print(f"\n{passed}/{len(graphql_files)} .graphql files passed validation.")
    if failed_files:
        print(f"{len(failed_files)} file(s) failed (may target internal endpoint).")
        sys.exit(1)
