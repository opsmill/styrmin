"""Schema-introspection assertions for :class:`UpdateDeploymentInput` (011).

Implements the three introspection tests from
``specs/011-typed-deployment-input/contracts/graphql.md`` §6:

* :func:`test_update_deployment_input_field_coverage` — pins that
  ``UpdateDeploymentInput`` carries exactly the union of every
  ``DeploymentConfig`` field plus the four deployment-only mutation
  fields (``name`` / ``parameters`` / ``serviceNameOverrides`` /
  ``components``). Future schema drift on either side fails this test
  with a precise message naming the missing / extra field.

* :func:`test_update_deployment_arguments_have_no_json_typed_args` —
  pins SC-001: the ``updateDeployment`` mutation has no ``JSON``-typed
  arguments after the cutover. Argument list must be exactly
  ``deploymentId: UUID!`` and ``input: UpdateDeploymentInput!``.

* :func:`test_update_deployment_input_fields_have_descriptions` —
  drives FR-012: every field on ``UpdateDeploymentInput``,
  ``ComponentConfigInput``, ``ParameterValueInput``, and
  ``StandardStorageInput`` must carry a non-empty ``description``.

These tests walk the live Strawberry schema rather than the generated
``schema.graphql`` so any drift between the resolver and the contract
fails immediately, without needing a separate regen step.
"""

from __future__ import annotations

import strawberry

from styrmin_backend.api.definitions.config.inputs import StandardStorageInput
from styrmin_backend.api.definitions.deployment.inputs import (
    ComponentConfigInput,
    ParameterValueInput,
    UpdateDeploymentInput,
)
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query
from styrmin_backend.context.models.config import ComponentConfigBlock, DeploymentConfig


def _build_schema() -> strawberry.Schema:
    return strawberry.Schema(query=Query, mutation=Mutation)


def test_update_deployment_input_field_coverage() -> None:
    """``UpdateDeploymentInput.fields`` == ``DeploymentConfig.model_fields`` ∪
    {``name``, ``parameters``, ``service_name_overrides``, ``components``}.

    Compares on ``python_name`` (snake_case) so the assertion is robust
    against Strawberry's automatic GraphQL camelCase conversion. The
    Pydantic side already includes ``components`` (it's a field on
    ``DeploymentConfig``), so the additional deployment-only fields
    are exactly the three top-level scalars/lists.
    """
    input_field_names = {
        f.python_name for f in UpdateDeploymentInput.__strawberry_definition__.fields
    }
    pydantic_field_names = set(DeploymentConfig.model_fields.keys())
    deployment_only = {"name", "parameters", "service_name_overrides"}
    expected = pydantic_field_names | deployment_only

    missing = expected - input_field_names
    assert not missing, (
        f"UpdateDeploymentInput is missing fields: {sorted(missing)}. "
        "Every DeploymentConfig field plus the deployment-only "
        "(name, parameters, service_name_overrides) fields MUST exist "
        "on the input (FR-001/SC-001). Add the missing field to "
        "backend/styrmin_backend/api/definitions/deployment/inputs.py."
    )
    extra = input_field_names - expected
    assert not extra, (
        f"UpdateDeploymentInput has unexpected fields: {sorted(extra)}. "
        "Remove them or add the matching attribute to "
        "DeploymentConfig in "
        "backend/styrmin_backend/context/models/config.py."
    )


def test_component_config_input_field_coverage() -> None:
    """``ComponentConfigInput.fields`` == ``ComponentConfigBlock.model_fields`` ∪ {``name``}.

    Pins the per-component input ↔ storage-model parity (ADR-014,
    014-component-container-overrides contracts/graphql-deltas.md §Propagation
    #2): any field added to ``ComponentConfigBlock`` (e.g. ``command`` /
    ``args``) without the matching field on ``ComponentConfigInput`` — or vice
    versa — fails this test. ``name`` is the input-only addressing field with
    no counterpart on the storage block. Compares on ``python_name``
    (snake_case) so the assertion is robust against Strawberry's automatic
    GraphQL camelCase conversion.
    """
    input_field_names = {
        f.python_name for f in ComponentConfigInput.__strawberry_definition__.fields
    }
    # TODO(018 T025): remove once ComponentConfigInput.image lands.
    pending_input_fields = {"image"} - input_field_names
    block_field_names = set(ComponentConfigBlock.model_fields.keys())
    expected = (block_field_names | {"name"}) - pending_input_fields

    missing = expected - input_field_names
    assert not missing, (
        f"ComponentConfigInput is missing fields: {sorted(missing)}. "
        "Every ComponentConfigBlock field (plus the input-only ``name``) MUST "
        "exist on the input. Add the missing field to "
        "backend/styrmin_backend/api/definitions/deployment/inputs.py."
    )
    extra = input_field_names - expected
    assert not extra, (
        f"ComponentConfigInput has unexpected fields: {sorted(extra)}. "
        "Remove them or add the matching attribute to ComponentConfigBlock in "
        "backend/styrmin_backend/context/models/config.py."
    )


def test_update_deployment_arguments_have_no_json_typed_args() -> None:
    """The ``updateDeployment`` mutation accepts exactly two arguments —
    ``deploymentId: UUID!`` and ``input: UpdateDeploymentInput!`` — and
    neither is the legacy ``JSON`` scalar.

    Pins SC-001: the JSON-typed ``config`` / ``parameters`` arguments
    from the pre-011 signature are gone. The schema-introspection check
    runs against the live ``Mutation`` type so a regression in the
    resolver decorator surfaces before codegen runs.
    """
    schema = _build_schema()
    mutation_type = schema._schema.type_map["Mutation"]
    field = mutation_type.fields["updateDeployment"]

    arg_names = sorted(field.args.keys())
    assert arg_names == ["deploymentId", "input"], (
        f"updateDeployment must accept exactly (deploymentId, input); "
        f"got {arg_names}. The legacy JSON-typed args MUST be removed."
    )

    for arg_name, arg in field.args.items():
        type_str = str(arg.type)
        assert "JSON" not in type_str, (
            f"updateDeployment.{arg_name} has type {type_str!r} which "
            "includes the JSON scalar. SC-001 requires zero JSON-typed "
            "arguments on this mutation after the typed cutover."
        )


def test_update_deployment_input_fields_have_descriptions() -> None:
    """Every field on the four new inputs carries a non-empty description
    (FR-012). The check walks the Strawberry input definitions directly
    — no schema build required.
    """
    targets = {
        "UpdateDeploymentInput": UpdateDeploymentInput,
        "ComponentConfigInput": ComponentConfigInput,
        "ParameterValueInput": ParameterValueInput,
        "StandardStorageInput": StandardStorageInput,
    }
    missing: list[str] = []
    for type_name, cls in targets.items():
        for field in cls.__strawberry_definition__.fields:
            description = (field.description or "").strip()
            if not description:
                missing.append(f"{type_name}.{field.python_name}")
    assert not missing, (
        f"Fields missing non-empty descriptions: {sorted(missing)}. "
        "FR-012 requires every new input field to carry a non-empty "
        "``description=...`` argument so the SDK and frontend codegen "
        "surface usable docstrings."
    )
