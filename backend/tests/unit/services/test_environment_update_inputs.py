"""Unit tests for ``UpdateEnvironmentInput`` conversion helpers (009 / US2).

Cover the contract of :func:`update_environment_input_to_dict`:

* every top-level field round-trips cleanly through
  ``EnvironmentConfig.model_validate(...)``;
* ``None`` (or :data:`strawberry.UNSET`) field → key omitted (full
  replacement: persisted row carries the unset state);
* empty list → preserved (operator explicitly cleared a list field);
* nested inputs serialize their fields recursively, also with
  ``None``-omission;
* enum values lower to the Pydantic-side ``Literal`` strings;
* duplicate env var names raise the typed ``DuplicateEnvVarNameError``
  rather than silently de-duplicating.
"""

from __future__ import annotations

import pytest

from styrmin_backend.api.definitions.environment.inputs import (
    DedicatedIngressInput,
    EnvVarInput,
    ExternalDnsEndpointsType,
    ExternalUrlScheme,
    IngressServiceConfigInput,
    PostRenderInjectionInput,
    ResourceRequirementsInput,
    ResourceSpecInput,
    SchedulingInput,
    TolerationEffect,
    TolerationInput,
    TolerationOperator,
    TopologySpreadConstraintInput,
    UpdateEnvironmentInput,
    WhenUnsatisfiable,
    update_environment_input_to_dict,
)
from styrmin_backend.context.models.config import EnvironmentConfig
from styrmin_backend.services.env_vars.exceptions import (
    DuplicateEnvVarNameError,
)


def test_empty_input_yields_empty_dict() -> None:
    """An ``UpdateEnvironmentInput()`` with every field at default
    serializes to ``{}`` — ``EnvironmentConfig`` accepts that as the
    fully-unset state.
    """
    result = update_environment_input_to_dict(UpdateEnvironmentInput())
    assert result == {}
    EnvironmentConfig.model_validate(result)


def test_env_vars_round_trip() -> None:
    """``env_vars: [EnvVarInput]`` flattens to the ``{name: value}`` dict
    shape that the Pydantic ``EnvironmentConfig`` validator expects.
    """
    input_obj = UpdateEnvironmentInput(
        env_vars=[
            EnvVarInput(name="OTEL_ENDPOINT", value="https://otel.staging"),
            EnvVarInput(name="LOG_LEVEL", value="info"),
        ],
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {
        "env_vars": {
            "OTEL_ENDPOINT": "https://otel.staging",
            "LOG_LEVEL": "info",
        }
    }
    EnvironmentConfig.model_validate(result)


def test_duplicate_env_var_name_raises_typed_error() -> None:
    """Duplicate env-var names in the input list are rejected with the
    typed :class:`DuplicateEnvVarNameError` so the GraphQL boundary can
    surface ``DUPLICATE_ENV_VAR_NAME``.
    """
    input_obj = UpdateEnvironmentInput(
        env_vars=[
            EnvVarInput(name="X", value="1"),
            EnvVarInput(name="X", value="2"),
        ],
    )
    with pytest.raises(DuplicateEnvVarNameError) as exc_info:
        update_environment_input_to_dict(input_obj)
    assert exc_info.value.name == "X"
    assert exc_info.value.scope == "environment"


def test_ip_whitelist_round_trip() -> None:
    input_obj = UpdateEnvironmentInput(ip_whitelist=["10.0.0.0/8", "192.168.0.0/16"])
    result = update_environment_input_to_dict(input_obj)
    assert result == {"ip_whitelist": ["10.0.0.0/8", "192.168.0.0/16"]}
    EnvironmentConfig.model_validate(result)


def test_empty_list_is_preserved() -> None:
    """An explicitly empty ``ip_whitelist`` survives the conversion
    (operator cleared the list — distinct from "field unset").
    """
    input_obj = UpdateEnvironmentInput(ip_whitelist=[])
    result = update_environment_input_to_dict(input_obj)
    assert result == {"ip_whitelist": []}


def test_full_replacement_omits_unset_fields() -> None:
    """When only ``env_vars`` is set, the output dict has only that key —
    every other top-level field is omitted (full-replacement semantics).
    """
    input_obj = UpdateEnvironmentInput(
        env_vars=[EnvVarInput(name="X", value="y")],
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {"env_vars": {"X": "y"}}
    assert "ip_whitelist" not in result
    assert "scheduling" not in result
    assert "dedicated_ingress" not in result


def test_external_url_scheme_enum_lowered_to_literal() -> None:
    """``ExternalUrlScheme.HTTPS`` lowers to ``"https"`` (the
    Pydantic-side ``Literal`` value).
    """
    input_obj = UpdateEnvironmentInput(external_url_scheme=ExternalUrlScheme.HTTPS)
    result = update_environment_input_to_dict(input_obj)
    assert result == {"external_url_scheme": "https"}
    EnvironmentConfig.model_validate(result)


def test_external_dns_endpoints_type_enum_lowered() -> None:
    input_obj = UpdateEnvironmentInput(
        external_dns_endpoints_type=ExternalDnsEndpointsType.NODE_EXTERNAL_IP,
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {"external_dns_endpoints_type": "NodeExternalIP"}
    EnvironmentConfig.model_validate(result)


def test_fqdn_suffix_and_port_scalars() -> None:
    input_obj = UpdateEnvironmentInput(
        fqdn_suffix="test.example.com",
        external_url_port=8443,
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {"fqdn_suffix": "test.example.com", "external_url_port": 8443}
    EnvironmentConfig.model_validate(result)


def test_dedicated_ingress_nested_round_trip() -> None:
    """A nested ``DedicatedIngressInput`` serialises recursively and the
    output dict validates against ``DedicatedIngressConfig``.
    """
    input_obj = UpdateEnvironmentInput(
        dedicated_ingress=DedicatedIngressInput(
            implementation="traefik",
            type="ingress",
            service=IngressServiceConfigInput(
                type="LoadBalancer",
                load_balancer_ip="10.0.0.1",
            ),
        ),
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {
        "dedicated_ingress": {
            "implementation": "traefik",
            "type": "ingress",
            "service": {
                "type": "LoadBalancer",
                "load_balancer_ip": "10.0.0.1",
            },
        }
    }
    EnvironmentConfig.model_validate(result)


def test_scheduling_runtime_class_round_trip() -> None:
    input_obj = UpdateEnvironmentInput(
        scheduling=SchedulingInput(runtime_class="kata"),
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {"scheduling": {"runtime_class": "kata"}}
    EnvironmentConfig.model_validate(result)


def test_scheduling_resources_round_trip() -> None:
    input_obj = UpdateEnvironmentInput(
        scheduling=SchedulingInput(
            resources=ResourceRequirementsInput(
                requests=ResourceSpecInput(cpu="100m", memory="256Mi"),
                limits=ResourceSpecInput(cpu="500m", memory="512Mi"),
            ),
        ),
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {
        "scheduling": {
            "resources": {
                "requests": {"cpu": "100m", "memory": "256Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            }
        }
    }
    EnvironmentConfig.model_validate(result)


def test_scheduling_tolerations_with_enums() -> None:
    """Toleration enums lower to their Pydantic-side ``Literal`` values."""
    input_obj = UpdateEnvironmentInput(
        scheduling=SchedulingInput(
            tolerations=[
                TolerationInput(
                    key="node-role.kubernetes.io/control-plane",
                    operator=TolerationOperator.EXISTS,
                    effect=TolerationEffect.NO_SCHEDULE,
                ),
            ],
        ),
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {
        "scheduling": {
            "tolerations": [
                {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ]
        }
    }
    EnvironmentConfig.model_validate(result)


def test_scheduling_topology_spread_constraint_with_enum() -> None:
    """``WhenUnsatisfiable`` enum lowers to ``DoNotSchedule``."""
    input_obj = UpdateEnvironmentInput(
        scheduling=SchedulingInput(
            topology_spread_constraints=[
                TopologySpreadConstraintInput(
                    max_skew=1,
                    topology_key="topology.kubernetes.io/zone",
                    when_unsatisfiable=WhenUnsatisfiable.DO_NOT_SCHEDULE,
                ),
            ],
        ),
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {
        "scheduling": {
            "topology_spread_constraints": [
                {
                    "max_skew": 1,
                    "topology_key": "topology.kubernetes.io/zone",
                    "when_unsatisfiable": "DoNotSchedule",
                }
            ]
        }
    }
    EnvironmentConfig.model_validate(result)


def test_scheduling_post_render_injection_round_trip() -> None:
    """``PostRenderInjectionInput`` carries booleans that survive the conversion."""
    input_obj = UpdateEnvironmentInput(
        scheduling=SchedulingInput(
            inject=PostRenderInjectionInput(tolerations=False, resources=True),
        ),
    )
    result = update_environment_input_to_dict(input_obj)
    assert result == {
        "scheduling": {"inject": {"tolerations": False, "resources": True}}
    }
    EnvironmentConfig.model_validate(result)


def test_mixed_fields_only_set_keys_appear() -> None:
    """Mixed input: env_vars + ip_whitelist set, scheduling None — output
    has only env_vars + ip_whitelist keys.
    """
    input_obj = UpdateEnvironmentInput(
        env_vars=[EnvVarInput(name="A", value="1")],
        ip_whitelist=["10.0.0.0/8"],
    )
    result = update_environment_input_to_dict(input_obj)
    assert set(result.keys()) == {"env_vars", "ip_whitelist"}
    EnvironmentConfig.model_validate(result)
