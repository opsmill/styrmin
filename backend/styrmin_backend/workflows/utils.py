from pathlib import Path
from typing import Any

import jsonschema

from styrmin_backend.utils import parse_json_file, parse_yaml_file


def load_variables_template(template_path: Path) -> dict[str, Any]:
    """Load the JSON variables template from the given path.

    Args:
        template_path (Path): Path to the variables template.

    Returns:
        dict[str, Any]: The variables template.
    """

    schema = parse_json_file(template_path)

    # Ensure the job configuration template is a valid JSON schema
    try:
        schema_validator = jsonschema.validators.validator_for(schema)
        schema_validator.check_schema(schema)
    except jsonschema.exceptions.SchemaError:
        raise

    return schema


def load_job_configuration_template(template_path: Path) -> dict[str, Any]:
    """Load the job JSON configuration template from the given path.

    Args:
        template_path (Path): Path to the job configuration template.

    Returns:
        dict[str, Any]: The job configuration template.
    """

    return parse_yaml_file(template_path)


def get_repository_name(repository_url: str) -> str:
    """Get the repository name from the given URL.

    Examples:
        >>> get_repository_name("https://github.com/opsmill/styrmin.git")
        "styrmin-mvp"

    Args:
        repository_url (str): The URL of the repository.

    Returns:
        str: The repository name.
    """

    return repository_url.split("/")[-1].split(".")[0]


def set_directory_pull_step(
    directory: str, repository_name: str, branch: str
) -> dict[str, Any]:
    """Set the working directory in a pull step.

    Args:
        directory (str): The local directory to set.
        repository_name (str): The name of the repository.
        branch (str): The branch of the repository.

    Returns:
        dict[str, Any]: The pull step.
    """

    return {
        "prefect.deployments.steps.set_working_directory": {
            "directory": f"/opt/prefect/{repository_name}-{branch}/{directory}",
        }
    }
