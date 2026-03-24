"""Provides the validation models for driver parameter definitions.

Driver parameters allow driver authors to declare typed configuration knobs
that users provide when creating or updating deployments.

Example in styrmin_driver.yaml:
    ```yaml
    spec:
      parameters:
        - name: replicas
          label: "Number of replicas"
          kind: integer
          default: 1
        - name: log_level
          label: "Log level"
          kind: enum
          values: ["debug", "info", "warning", "error"]
          default: "info"
    ```
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator


class DriverParameterKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"


class DriverParameterDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    kind: DriverParameterKind
    default: str | int | bool | None = None
    values: list[str] | None = None

    @model_validator(mode="after")
    def validate_parameter(self) -> "DriverParameterDefinition":
        # Enum kind requires a non-empty values list
        if self.kind == DriverParameterKind.ENUM:
            if not self.values:
                raise ValueError(
                    f"Parameter '{self.name}': enum kind requires a non-empty 'values' list"
                )
        else:
            if self.values is not None:
                raise ValueError(
                    f"Parameter '{self.name}': 'values' is only allowed for enum kind"
                )

        # Validate default matches declared kind
        if self.default is not None:
            self._validate_default_type()

        return self

    def _validate_default_type(self) -> None:
        expected_types: dict[DriverParameterKind, type] = {
            DriverParameterKind.STRING: str,
            DriverParameterKind.INTEGER: int,
            DriverParameterKind.BOOLEAN: bool,
            DriverParameterKind.ENUM: str,
        }
        expected = expected_types[self.kind]

        # bool is a subclass of int in Python, so check bool before int
        if self.kind == DriverParameterKind.INTEGER and isinstance(self.default, bool):
            raise ValueError(
                f"Parameter '{self.name}': default value must be {expected.__name__}, "
                f"got {type(self.default).__name__}"
            )

        if not isinstance(self.default, expected):
            raise ValueError(
                f"Parameter '{self.name}': default value must be {expected.__name__}, "
                f"got {type(self.default).__name__}"
            )

        # Enum default must be in the values list
        if self.kind == DriverParameterKind.ENUM and self.values:
            if self.default not in self.values:
                raise ValueError(
                    f"Parameter '{self.name}': default value '{self.default}' "
                    f"is not in allowed values {self.values}"
                )


def validate_parameter_names_unique(
    parameters: list[DriverParameterDefinition],
) -> list[DriverParameterDefinition]:
    """Validate that parameter names are unique within a list."""
    names = [p.name for p in parameters]
    duplicates = [name for name in names if names.count(name) > 1]
    if duplicates:
        raise ValueError(f"Duplicate parameter names: {sorted(set(duplicates))}")
    return parameters
