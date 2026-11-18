import json
from abc import abstractmethod
from pathlib import Path
from typing import Any

import yaml

from styrmin_sdk.driver_format.errors import (
    ParsingError,
)
from styrmin_sdk.driver_format.models.structure.resource import Syntax


class Parser:
    """The abstract parser class."""

    @abstractmethod
    def parse(self, path: Path) -> Any:
        """Parse the object.

        Raises:
            ParsingError: If the parsing failed.
        """
        raise NotImplementedError


class YamlParser(Parser):
    def parse(self, path: Path) -> Any:
        try:
            with open(path) as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as err:
            raise ParsingError(f"Error while parsing the driver resource file: {err!s}")


class JsonParser(Parser):
    def parse(self, path: Path) -> Any:
        try:
            with open(path) as f:
                return json.load(f)
        except json.JSONDecodeError as err:
            raise ParsingError(f"Error while parsing the driver resource file: {err!s}")


class StringParser(Parser):
    def parse(self, path: Path) -> str:
        with open(path) as f:
            return f.read()


def get_parser(syntax: Syntax) -> Parser:
    """Get the parser based on the syntax.

    Args:
        syntax (Syntax): The syntax.

    Returns:
        Parser: The parser.
    """
    match syntax:
        case Syntax.YAML:
            return YamlParser()
        case Syntax.JSON:
            return JsonParser()
        case Syntax.STR | Syntax.PYTHON:
            return StringParser()
        case _:
            raise ValueError(f"Unsupported syntax: {syntax!r}")
