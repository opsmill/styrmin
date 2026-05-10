"""Driver-side env-var documentation models (US4 / data-model.md §3).

Drivers may include a ``spec.env_vars`` block listing env vars the app
respects. Each entry is **doc-only**: it does not constrain or default
operator-set values (FR-015). The model below validates the entry shape
at driver load time so registration aborts on a malformed declaration
(FR-013, FR-014).

Cross-field validation that needs the parent ``Specification`` (every
``components`` entry must reference a declared component) lives in
``services/driver/validators.py`` and is invoked from the loader.
"""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from styrmin_backend.services.env_vars.exceptions import InvalidEnvVarNameError
from styrmin_backend.services.env_vars.validator import _ENV_VAR_NAME_RE


class DriverEnvVarLevel(str, Enum):
    """Scope at which a documented env var is meaningful.

    - ``DEPLOYMENT``: the env var applies broadly across the deployment.
    - ``COMPONENT``: the env var applies only to the listed components.
    """

    DEPLOYMENT = "deployment"
    COMPONENT = "component"


class DriverEnvVarDoc(BaseModel):
    """Doc-only declaration of an env var the driver's app respects.

    The entry surfaces in the driver detail view (``ApplicationDriverVersion.envVars``)
    and is purely informational — it does not validate, default, or
    constrain operator-set env var values (FR-015).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="POSIX env var name")
    description: str
    level: DriverEnvVarLevel
    components: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        # FR-006: env var names follow the POSIX-portable regex. The driver
        # loader path raises without an input ``scope`` so the metadata
        # stays minimal for driver-load-time errors (the operator-input
        # rejection path in ``services/env_vars/validator.py`` does set a
        # scope).
        if not _ENV_VAR_NAME_RE.match(v):
            raise InvalidEnvVarNameError(name=v)
        return v

    @model_validator(mode="after")
    def _validate_components_for_component_level(self) -> Self:
        # FR-013: ``level=component`` MUST list at least one target
        # component; ``level=deployment`` MUST NOT name components.
        if self.level is DriverEnvVarLevel.COMPONENT and not self.components:
            raise ValueError(
                f"env var doc '{self.name}': level='component' requires a "
                "non-empty `components` list"
            )
        if self.level is DriverEnvVarLevel.DEPLOYMENT and self.components:
            raise ValueError(
                f"env var doc '{self.name}': level='deployment' MUST NOT "
                "name components"
            )
        return self


def validate_env_var_doc_names_unique(
    env_vars: list[DriverEnvVarDoc],
) -> list[DriverEnvVarDoc]:
    """Validate that env var doc names are unique within a driver's list.

    Mirrors ``validate_parameter_names_unique`` (FR-013).
    """
    names = [doc.name for doc in env_vars]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Duplicate driver env var doc names: {duplicates}")
    return env_vars
