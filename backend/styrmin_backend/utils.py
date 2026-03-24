import json
from pathlib import Path
from typing import Any

import yaml


def parse_yaml_file(file_path: Path) -> dict[str, Any]:
    """Parse the YAML file from the given path.

    Args:
        file_path (Path): Path to the YAML file.

    Returns:
        dict[str, Any]: The parsed YAML file.
    """

    with open(file_path, "r") as file:
        return yaml.safe_load(file)


def parse_json_file(file_path: Path) -> dict[str, Any]:
    """Parse the JSON file from the given path.

    Args:
        file_path (Path): Path to the JSON file.

    Returns:
        dict[str, Any]: The parsed JSON file.
    """

    with open(file_path, "r") as file:
        return json.load(file)
