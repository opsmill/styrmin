from pathlib import Path

from pydantic import BaseModel

from styrmin_sdk.driver_format.models.structure.resource import (
    ResourceFile,
    Role,
    Syntax,
)


class DriverFileNames(BaseModel):
    """The names of the files of a driver directory.

    The defaults are the names that the documentation gives. The server can change them
    with its ``STYRMIN_DRIVER_*`` settings and passes the result here.
    """

    spec_file: str = "driver.styrmin.yml"
    values_template: str = "values.j2.yml"
    actions_code: str = "actions.py"


class DriverDirectory:
    """The driver directory model.

    The driver directory model represents the structure of the driver directory.
    It defines the resources that are expected to be present in the driver directory, along with
    their roles, syntaxes, and paths.
    """

    def __init__(
        self,
        root_path: Path,
        file_names: DriverFileNames | None = None,
    ) -> None:
        names = file_names or DriverFileNames()
        self.driver_spec: ResourceFile = ResourceFile(
            role=Role.DRIVER_SPEC,
            syntax=Syntax.YAML,
            path=root_path / names.spec_file,
        )
        self.values_template: ResourceFile = ResourceFile(
            role=Role.VALUES_TEMPLATE,
            syntax=Syntax.STR,
            path=root_path / names.values_template,
            optional=True,
        )
        self.actions_code: ResourceFile = ResourceFile(
            role=Role.ACTIONS_CODE,
            syntax=Syntax.PYTHON,
            path=root_path / names.actions_code,
            optional=True,
        )
