"""Tests for the export commands."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.cli.export import export_app


MOCK_SDL = """\
type Query {
  hello: String
}

type Mutation {
  createUser(name: String!): User
}

type User {
  id: ID!
  name: String!
}
"""


def test_export_graphql_schema_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that export graphql-schema --help shows expected options."""
    with pytest.raises(SystemExit) as exc_info:
        export_app(["graphql-schema", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "OUTPUT-FILE" in output or "output-file" in output.lower()


def test_export_graphql_schema_creates_file(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Test that export graphql-schema creates a file at specified path."""
    # Mock strawberry.Schema to return predictable SDL
    mock_schema_class = mocker.patch("styrmin_backend.cli.export.strawberry.Schema")
    mock_schema_instance = mock_schema_class.return_value
    mock_schema_instance.__str__ = mocker.Mock(return_value=MOCK_SDL)

    output_path = tmp_path / "schema.graphql"

    with pytest.raises(SystemExit) as exc_info:
        export_app(["graphql-schema", str(output_path)])

    assert exc_info.value.code == 0
    assert output_path.exists(), f"Schema file was not created at {output_path}"
    content = output_path.read_text()
    assert len(content) > 0, "Schema file is empty"


def test_exported_schema_contains_query_type(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Test that exported schema contains Query type."""
    mock_schema_class = mocker.patch("styrmin_backend.cli.export.strawberry.Schema")
    mock_schema_instance = mock_schema_class.return_value
    mock_schema_instance.__str__ = mocker.Mock(return_value=MOCK_SDL)

    output_path = tmp_path / "schema.graphql"

    with pytest.raises(SystemExit) as exc_info:
        export_app(["graphql-schema", str(output_path)])

    assert exc_info.value.code == 0
    content = output_path.read_text()
    assert "type Query" in content, "Schema should contain Query type"


def test_exported_schema_contains_mutation_type(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Test that exported schema contains Mutation type."""
    mock_schema_class = mocker.patch("styrmin_backend.cli.export.strawberry.Schema")
    mock_schema_instance = mock_schema_class.return_value
    mock_schema_instance.__str__ = mocker.Mock(return_value=MOCK_SDL)

    output_path = tmp_path / "schema.graphql"

    with pytest.raises(SystemExit) as exc_info:
        export_app(["graphql-schema", str(output_path)])

    assert exc_info.value.code == 0
    content = output_path.read_text()
    assert "type Mutation" in content, "Schema should contain Mutation type"


def test_export_graphql_schema_uses_correct_types(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Test that export uses Query and Mutation from styrmin_backend.api.schema."""
    mock_schema_class = mocker.patch("styrmin_backend.cli.export.strawberry.Schema")
    mock_schema_instance = mock_schema_class.return_value
    mock_schema_instance.__str__ = mocker.Mock(return_value=MOCK_SDL)

    mock_query = mocker.patch("styrmin_backend.cli.export.Query")
    mock_mutation = mocker.patch("styrmin_backend.cli.export.Mutation")

    output_path = tmp_path / "schema.graphql"

    with pytest.raises(SystemExit) as exc_info:
        export_app(["graphql-schema", str(output_path)])

    assert exc_info.value.code == 0
    mock_schema_class.assert_called_once_with(query=mock_query, mutation=mock_mutation)


def test_export_graphql_schema_handles_write_error(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Test that export handles file write errors gracefully."""
    mock_schema_class = mocker.patch("styrmin_backend.cli.export.strawberry.Schema")
    mock_schema_instance = mock_schema_class.return_value
    mock_schema_instance.__str__ = mocker.Mock(return_value=MOCK_SDL)

    # Use a path that will fail (directory doesn't exist)
    invalid_path = "/nonexistent/directory/schema.graphql"

    with pytest.raises(SystemExit) as exc_info:
        export_app(["graphql-schema", invalid_path])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Error writing schema file" in output
