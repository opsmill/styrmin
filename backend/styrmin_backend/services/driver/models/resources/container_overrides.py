"""Driver-side container-override documentation models (014 / US6).

Drivers may include a ``spec.container_overrides`` block listing the components
whose container ``command``/``args`` the operator may override. Each entry is
**doc-only**: it does not constrain or default operator-set values, and the
platform does NOT require a declared component to actually consume the override
(FR-010, US6 Sc.3 — declared-but-unwired stores-but-never-applies). The model
below validates the entry shape at driver load time so registration aborts on a
malformed declaration. Mirrors ``resources/env_vars.py``.

Cross-field validation that needs the parent ``Specification`` (every
``component`` reference must resolve to a declared component) lives in
``services/driver/validators.py`` and is invoked from the loader.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DriverContainerOverrideDoc(BaseModel):
    """Doc-only declaration that a component's ``command``/``args`` are overridable.

    Surfaces in the driver detail view
    (``ApplicationDriverVersion.containerOverrides``) and is purely
    informational — it does not validate, default, or constrain operator-set
    override values (FR-010/FR-011).
    """

    model_config = ConfigDict(extra="forbid")

    component: str = Field(
        ..., description="The component whose container command/args are overridable."
    )
    description: str = ""
    container: str | None = Field(
        default=None,
        description="Informational: which rendered container the override targets.",
    )
    command: bool = Field(
        default=False, description="Advertises that ``command`` is overridable."
    )
    args: bool = Field(
        default=False, description="Advertises that ``args`` is overridable."
    )


def validate_container_override_doc_components_unique(
    container_overrides: list[DriverContainerOverrideDoc],
) -> list[DriverContainerOverrideDoc]:
    """Validate that each declared component appears at most once.

    One ``container_overrides`` block per component (mirrors
    ``validate_env_var_doc_names_unique`` but keyed on ``component``).
    """
    components = [doc.component for doc in container_overrides]
    duplicates = sorted({c for c in components if components.count(c) > 1})
    if duplicates:
        raise ValueError(
            f"Duplicate driver container_overrides components: {duplicates}"
        )
    return container_overrides
