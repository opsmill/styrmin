from pathlib import Path

import pytest

from styrmin_backend.services.driver.exceptions import (
    ParsingError,
)
from styrmin_backend.services.driver.models.structure.resource import Syntax
from styrmin_backend.services.driver.parsers import (
    JsonParser,
    StringParser,
    YamlParser,
    get_parser,
)


@pytest.mark.parametrize(
    "syntax, expected_parser",
    [
        (Syntax.JSON, JsonParser),
        (Syntax.YAML, YamlParser),
        (Syntax.STR, StringParser),
    ],
)
def test_parser_factory(syntax, expected_parser):
    """Test the parser factory."""
    parser = get_parser(syntax)
    assert isinstance(parser, expected_parser)


def test_parser_factory_with_invalid_syntax():
    """Test the parser factory with an invalid syntax."""
    with pytest.raises(ValueError):
        get_parser("invalid-syntax")


def test_yaml_parser():
    """Test the parsing of the local driver spec file."""
    spec_path = Path(__file__).parent / "fixtures" / "syntax" / "valid.yaml"
    parser = YamlParser()
    data = parser.parse(spec_path)

    assert isinstance(data, dict)


def test_yaml_parser_with_invalid_syntax():
    """Test the parsing of an invalid file."""
    spec_path = Path(__file__).parent / "fixtures" / "syntax" / "invalid.yaml"
    parser = YamlParser()
    with pytest.raises(ParsingError):
        parser.parse(spec_path)


def test_json_parser():
    """Test the parsing of the local driver spec file."""
    spec_path = Path(__file__).parent / "fixtures" / "syntax" / "valid.json"
    parser = JsonParser()
    data = parser.parse(spec_path)

    assert isinstance(data, dict)


def test_json_parser_with_invalid_syntax():
    """Test the parsing of an invalid file."""
    spec_path = Path(__file__).parent / "fixtures" / "syntax" / "invalid.json"
    parser = JsonParser()
    with pytest.raises(ParsingError):
        parser.parse(spec_path)
