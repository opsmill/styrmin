"""The shape of a config rejection as an API client sees it.

Every config surface (cluster create, environment create/update, deploy,
deployment update) funnels through ``validate_*_config``, so whatever those
functions put on the ``Invalid*ContextError`` is what reaches the caller through
the GraphQL ``errors[].message``.

Two things are pinned here, and they pull against each other:

* **Keep the actionable part.** 016 / FR-004 requires the rejection to name the
  offending field and carry the syntax hint, so an operator can fix the value
  without reading our source. That is why the message is derived from Pydantic
  rather than replaced with a generic "invalid config".
* **Drop the framework noise.** ``str(ValidationError)`` also emits the internal
  model class name, a ``type=`` tag, an ``input_value=`` echo, a
  ``pydantic.dev`` URL, and newlines — none of which the caller can act on, and
  none of which any other typed error in this project emits.

The nested case is called out separately because it is the one that can quietly
regress: a ``model_validator`` on a submodel reports the *entire submodel dict*
as its ``input``, so a formatter that reached for ``input`` would dump a large
blob for exactly the configs that are hardest to debug.

The last section covers the fourth config surface, which does not go through
``validate_*_config`` at all: ``resolve_global_context`` validates the
*components* context inline and reports it as a plain ``ContextError``. It is
held to the same message shape, and it is where the blob risk above is worst —
a component's ``config`` is a driver-defined arbitrary section, so ``input`` can
be the whole thing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.context.exceptions import (
    ContextError,
    InvalidClusterContextError,
    InvalidDeploymentContextError,
    InvalidEnvironmentContextError,
)
from styrmin_backend.context.models.input import (
    ComponentConfigInput,
    ComponentInput,
    ContextInput,
    IdentifierInput,
    Label,
)
from styrmin_backend.context.resolvers import resolve_global_context
from styrmin_backend.context.validators import (
    validate_cluster_config,
    validate_deployment_config,
    validate_environment_config,
)

# Fragments of Pydantic's full repr that must not reach an API client. Each is
# either an implementation detail (the model class name, the error-type tag) or
# an echo of what the caller already sent.
PYDANTIC_REPR_NOISE = (
    "validation error",
    "EnvironmentConfig",
    "ClusterConfig",
    "DeploymentConfig",
    "type=value_error",
    "input_value=",
    "pydantic.dev",
    "For further information",
)

VALIDATORS = (
    (validate_cluster_config, InvalidClusterContextError),
    (validate_environment_config, InvalidEnvironmentContextError),
    (validate_deployment_config, InvalidDeploymentContextError),
)


@pytest.mark.parametrize(
    ("validate", "error_type"), VALIDATORS, ids=lambda v: getattr(v, "__name__", str(v))
)
def test_malformed_backup_ttl_keeps_the_field_name_and_the_syntax_hint(
    validate, error_type
) -> None:
    """FR-004's contract survives at every scope: which field, and how to fix it.

    This is the half that must not be traded away when trimming the message —
    existing propagation coverage
    (``test_update_environment_rejects_malformed_backup_ttl``) asserts both
    fragments through the GraphQL boundary.
    """
    with pytest.raises(error_type) as exc_info:
        validate({"backup_ttl": "30d"})

    message = str(exc_info.value)
    assert "backup_ttl" in message
    assert "720h" in message


@pytest.mark.parametrize(
    ("validate", "error_type"), VALIDATORS, ids=lambda v: getattr(v, "__name__", str(v))
)
def test_rejection_message_carries_no_pydantic_framework_noise(
    validate, error_type
) -> None:
    """The message is ours, not a Pydantic repr — and it is one line.

    Single-line matters for consistency: every other typed error in the project
    is a single sentence, and a multi-line ``errors[].message`` renders badly in
    the CLI and the web UI alike.
    """
    with pytest.raises(error_type) as exc_info:
        validate({"backup_ttl": "30d"})

    message = str(exc_info.value)
    assert "\n" not in message, message
    for fragment in PYDANTIC_REPR_NOISE:
        assert fragment not in message, f"{fragment!r} leaked into: {message!r}"

    # ``input_value=`` is the mechanism; ``30d`` is the caller's own input. It
    # is not a secret, but echoing it adds nothing the field name does not.
    assert "input_value" not in message


def test_unknown_key_is_named_rather_than_described_generically() -> None:
    """A typo'd key still identifies itself, which is the only actionable part."""
    with pytest.raises(InvalidClusterContextError) as exc_info:
        validate_cluster_config({"invalid_key": "value"})

    message = str(exc_info.value)
    assert "invalid_key" in message
    assert "\n" not in message, message


def test_nested_model_validator_reports_a_path_not_the_submodel_blob() -> None:
    """A submodel failure names the dotted path and omits the submodel dict.

    ``ResourceSpec._validate_quantities`` is a ``model_validator(mode="after")``,
    so Pydantic attaches the whole ``requests`` dict to the error as ``input``.
    The message must locate the failure (``scheduling.resources.requests``) and
    explain it, without pasting the dict back at the caller — the naive
    formatting this guards against grows with the size of the config.
    """
    with pytest.raises(InvalidDeploymentContextError) as exc_info:
        validate_deployment_config(
            {
                "scheduling": {
                    "resources": {
                        "requests": {
                            "cpu": "not-a-quantity",
                            # Sibling values chosen so they do not appear in the
                            # quantity validator's own "e.g." hint — anything
                            # matching that would make the assertions below
                            # pass or fail for the wrong reason.
                            "memory": "777Mi",
                            "ephemeral_storage": "9Gi",
                        }
                    }
                }
            }
        )

    message = str(exc_info.value)
    assert "scheduling.resources.requests" in message, message
    assert "not-a-quantity" in message, message
    assert "\n" not in message, message
    # The submodel dict's *other* members are what a blob dump would drag in:
    # Pydantic attaches ``input={'cpu': ..., 'memory': '777Mi',
    # 'ephemeral_storage': '9Gi'}`` to this error.
    assert "777Mi" not in message, message
    assert "9Gi" not in message, message
    assert "ephemeral_storage" not in message, message
    for fragment in PYDANTIC_REPR_NOISE:
        assert fragment not in message, f"{fragment!r} leaked into: {message!r}"


def test_nested_list_element_failure_reports_its_index() -> None:
    """A failure inside a list of submodels keeps the element's position.

    ``AffinityTerm._require_one_selector`` fires on the term itself, so without
    the index the operator cannot tell which of several ``required`` terms is
    wrong.
    """
    with pytest.raises(InvalidDeploymentContextError) as exc_info:
        validate_deployment_config(
            {
                "scheduling": {
                    "pod_affinity": {
                        "required": [
                            {
                                "topology_key": "kubernetes.io/hostname",
                                "label_selector": {"match_labels": {"app": "web"}},
                            },
                            {"topology_key": "kubernetes.io/hostname"},
                        ]
                    }
                }
            }
        )

    message = str(exc_info.value)
    assert "scheduling.pod_affinity.required.1" in message, message
    assert "label_selector" in message, message


def test_multiple_failures_are_all_reported_on_one_line() -> None:
    """Reporting only the first failure would hide work from the operator."""
    with pytest.raises(InvalidEnvironmentContextError) as exc_info:
        validate_environment_config({"backup_ttl": "30d", "external_url_port": 99999})

    message = str(exc_info.value)
    assert "backup_ttl" in message
    assert "external_url_port" in message
    assert "\n" not in message, message


# ---------------------------------------------------------------------------
# The components surface (resolve_global_context, not validate_*_config)
# ---------------------------------------------------------------------------

#: The prefix ``resolve_global_context`` has always put in front of the
#: components rejection. Callers see it through ``errors[].message``, so it is
#: part of the contract and survives the message trimming.
COMPONENTS_PREFIX = "The components context validation failed."

#: As :data:`PYDANTIC_REPR_NOISE`, for the model this surface validates against
#: and the error kinds it produces.
COMPONENTS_REPR_NOISE = (
    "validation error",
    "ComponentContext",
    "type=missing",
    "type=string_type",
    "input_value=",
    "input_type=",
    "pydantic.dev",
    "For further information",
)

#: A driver-defined arbitrary section on the component's ``config``. None of
#: these names are declared by ``ComponentContext``, so nothing in a well-formed
#: message has any reason to mention them — but Pydantic attaches the whole dict
#: to a ``config.identifier`` failure as ``input``.
ARBITRARY_SECTION = {
    "persistence": {
        "size": "8Gi",
        "storageClass": "fast-ssd",
        "secretRef": "db-credentials",
    },
    "replicas": 3,
}


def _context_input(components: list[ComponentInput]) -> ContextInput:
    """Build the smallest ``ContextInput`` that reaches the components block.

    Everything other than ``components`` is inert filler — the components
    context is resolved first, so a rejection happens before any of it is read.
    It still has to be well-formed, which is what
    :func:`test_a_well_formed_components_context_resolves` confirms.
    """
    deployment_id = uuid4()
    return ContextInput.model_validate(
        {
            "config": {"cluster": {}, "environment": {}, "deployment": {}},
            "instance": {
                "deployment_id": deployment_id,
                "namespace": f"styrmin-{deployment_id}",
                "release_reference": f"styrmin-{deployment_id}",
            },
            "application": {
                "name": "simple-app",
                "version": "0.1.0",
                "chart": {
                    "id": uuid4(),
                    "name": "simple-app",
                    "version": "0.1.0",
                    "values_template": "{}",
                },
                "repository": {"id": uuid4(), "url": "https://charts.example.test"},
            },
            "components": components,
            "environment_name": "dev",
        }
    )


def test_a_well_formed_components_context_resolves() -> None:
    """Guards the two rejection tests below from passing for the wrong reason.

    They assert on the *content* of a message, which proves nothing if the
    filler around ``components`` is what fails. This pins that the happy path
    through :func:`_context_input` resolves cleanly.
    """
    component = ComponentInput.model_validate(
        {
            "name": "web",
            "enabled": True,
            "config": {"identifier": {"label": {"app": "web"}}} | ARBITRARY_SECTION,
        }
    )

    context = resolve_global_context(context_input=_context_input([component]))

    assert context.components is not None
    assert context.components["web"].enabled is True


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_components_rejection_names_the_field_and_drops_the_pydantic_repr() -> None:
    """Same message shape as every other config surface, same guarantees kept.

    ``ComponentInput`` and ``ComponentContext`` declare the same shape, so
    reaching this branch means a value was assembled in-process without
    re-validation — hence ``model_construct`` here. Pydantic accepts a model
    instance as-is, so the bad label survives to ``model_dump``.
    """
    component = ComponentInput(
        name="web",
        enabled=True,
        config=ComponentConfigInput(
            identifier=IdentifierInput(label=Label.model_construct(root={"app": 42})),
            **ARBITRARY_SECTION,
        ),
    )

    with pytest.raises(ContextError) as exc_info:
        resolve_global_context(context_input=_context_input([component]))

    # The exception type is not one of the ``Invalid*ContextError`` family — this
    # surface has always raised the base ``ContextError``, and the GraphQL layer
    # maps it accordingly, so trimming the message must not change it.
    assert type(exc_info.value) is ContextError

    message = str(exc_info.value)
    assert message.startswith(COMPONENTS_PREFIX), message
    # Which component field is wrong, down to the offending label key.
    assert "config.identifier.label.app" in message, message
    assert "\n" not in message, message
    for fragment in COMPONENTS_REPR_NOISE:
        assert fragment not in message, f"{fragment!r} leaked into: {message!r}"


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_components_rejection_does_not_echo_the_arbitrary_config_section() -> None:
    """The blob case, and the reason this surface matters most.

    A missing ``config.identifier`` makes Pydantic attach the *entire* component
    config to the error as ``input`` — and unlike the typed config models, that
    dict is whatever the driver declared, so its size and contents are
    unbounded. The message must locate the failure and stop there.
    """
    component = ComponentInput.model_construct(
        name="web",
        enabled=True,
        config=ComponentConfigInput.model_construct(**ARBITRARY_SECTION),
    )

    with pytest.raises(ContextError) as exc_info:
        resolve_global_context(context_input=_context_input([component]))

    message = str(exc_info.value)
    assert message.startswith(COMPONENTS_PREFIX), message
    assert "config.identifier" in message, message
    assert "\n" not in message, message
    # Nothing from the driver's own section comes back with it.
    for leaked in ("persistence", "storageClass", "fast-ssd", "db-credentials"):
        assert leaked not in message, f"{leaked!r} leaked into: {message!r}"
    for fragment in COMPONENTS_REPR_NOISE:
        assert fragment not in message, f"{fragment!r} leaked into: {message!r}"
