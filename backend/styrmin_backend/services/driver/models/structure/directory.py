from pathlib import Path

from styrmin_backend import config
from styrmin_backend.services.driver.models.structure.resource import (
    ResourceFile,
    Role,
    Syntax,
)


class DriverDirectory:
    """The driver directory model.

    The driver directory model represents the structure of the driver directory.
    It defines the resources that are expected to be present in the driver directory, along with
    their roles, syntaxes, and paths.
    """

    def __init__(
        self,
        root_path: Path,
    ):
        self.driver_spec: ResourceFile = ResourceFile(
            role=Role.DRIVER_SPEC,
            syntax=Syntax.YAML,
            path=root_path / config.SETTINGS.driver.spec_file,
        )
        self.values_template: ResourceFile = ResourceFile(
            role=Role.VALUES_TEMPLATE,
            syntax=Syntax.STR,
            path=root_path / config.SETTINGS.driver.values_template,
            optional=True,
        )
        self.actions_code: ResourceFile = ResourceFile(
            role=Role.ACTIONS_CODE,
            syntax=Syntax.PYTHON,
            path=root_path / config.SETTINGS.driver.actions_code_file,
            optional=True,
        )
