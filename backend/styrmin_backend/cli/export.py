"""Export commands for Styrmin CLI."""

from pathlib import Path

import strawberry
from cyclopts import App
from rich.console import Console
from strawberry.schema.config import StrawberryConfig

from styrmin_backend.api.scalars import SCALAR_MAP
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query

export_app = App(name="export", help="Export commands (schemas, data).")
console = Console()


@export_app.command(name="graphql-schema")
def graphql_schema(output_file: Path) -> None:
    """Export the public GraphQL schema to a file in SDL format.

    Parameters
    ----------
    output_file
        Path to write the GraphQL schema file.

    """
    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        config=StrawberryConfig(scalar_map=SCALAR_MAP),
    )
    sdl_content = str(schema)

    try:
        output_file.write_text(sdl_content)
        console.print(
            f"[bold green]GraphQL schema exported to {output_file}[/bold green]"
        )
    except OSError as exc:
        console.print(f"[bold red]Error writing schema file: {exc}[/bold red]")
        raise SystemExit(1) from exc
