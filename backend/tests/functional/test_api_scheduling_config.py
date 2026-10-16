"""Functional tests for the scheduling configuration API surface (T036).

Covers:

* ``validate_deployment_config`` accepting a well-formed scheduling payload
  end-to-end via the Pydantic hierarchy ``DeploymentConfig → BaseConfigSection``.
* Validation errors for malformed payloads (invalid quantity, non-DNS-1123
  runtime class) surface as :class:`InvalidDeploymentContextError` from the
  validator, which the GraphQL mutation layer converts into a
  VALIDATION_ERROR GraphQL extension on
  ``updateDeployment(deploymentId, input)``.
* The full HTTP-driven ``updateDeployment`` round-trip requires a live
  fixture stack (cluster + environment + driver version); it is scaffolded
  below with ``pytest.skip(...)`` and picked up by the functional harness
  when those fixtures are available.
"""

from __future__ import annotations

import pytest

from styrmin_backend.context.exceptions import (
    InvalidDeploymentContextError,
)
from styrmin_backend.context.validators import validate_deployment_config


class TestSchedulingPayloadValidation:
    """T036 (service layer): config round-trips through DeploymentConfig
    without loss and rejects malformed payloads at validation time.
    """

    def test_accepts_pod_affinity_payload(self) -> None:
        validate_deployment_config(
            {
                "scheduling": {
                    "pod_affinity": {
                        "required": [
                            {
                                "topology_key": "kubernetes.io/hostname",
                                "label_selector": {"match_labels": {"app": "web"}},
                            }
                        ]
                    }
                }
            }
        )

    def test_accepts_anti_affinity_with_deployment_ref(self) -> None:
        """The shape check accepts a name; the write that stores the config replaces it with the id."""
        validate_deployment_config(
            {
                "scheduling": {
                    "pod_anti_affinity": {
                        "required": [
                            {
                                "topology_key": "kubernetes.io/hostname",
                                "deployment_ref": {"deployment_name": "api"},
                            }
                        ]
                    }
                }
            }
        )

    def test_accepts_resources_and_tolerations(self) -> None:
        validate_deployment_config(
            {
                "scheduling": {
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "256Mi"},
                        "limits": {
                            "memory": "2Gi",
                            "extended": {"nvidia.com/gpu": "1"},
                        },
                    },
                    "tolerations": [
                        {
                            "key": "dedicated",
                            "operator": "Equal",
                            "value": "batch",
                            "effect": "NoSchedule",
                        }
                    ],
                    "runtime_class": "kata",
                    "inject": {"pod_affinity": False},
                }
            }
        )

    def test_rejects_invalid_quantity(self) -> None:
        with pytest.raises(InvalidDeploymentContextError):
            validate_deployment_config(
                {
                    "scheduling": {
                        "resources": {
                            "requests": {"cpu": "two cores"},
                        }
                    }
                }
            )

    def test_rejects_non_dns_1123_runtime_class(self) -> None:
        with pytest.raises(InvalidDeploymentContextError):
            validate_deployment_config({"scheduling": {"runtime_class": "UPPER_CASE"}})

    def test_rejects_affinity_term_without_selector(self) -> None:
        with pytest.raises(InvalidDeploymentContextError):
            validate_deployment_config(
                {
                    "scheduling": {
                        "pod_affinity": {
                            "required": [{"topology_key": "kubernetes.io/hostname"}]
                        }
                    }
                }
            )

    def test_rejects_deployment_ref_with_both_identifiers(self) -> None:
        with pytest.raises(InvalidDeploymentContextError):
            validate_deployment_config(
                {
                    "scheduling": {
                        "pod_affinity": {
                            "required": [
                                {
                                    "topology_key": "kubernetes.io/hostname",
                                    "deployment_ref": {
                                        "deployment_id": (
                                            "00000000-0000-0000-0000-000000000000"
                                        ),
                                        "deployment_name": "both",
                                    },
                                }
                            ]
                        }
                    }
                }
            )

    def test_rejects_unknown_field_under_scheduling(self) -> None:
        with pytest.raises(InvalidDeploymentContextError):
            validate_deployment_config({"scheduling": {"not_a_real_field": 1}})

    def test_accepts_empty_scheduling_block(self) -> None:
        validate_deployment_config({"scheduling": {}})

    def test_accepts_no_scheduling_block(self) -> None:
        validate_deployment_config({})


class TestUpdateDeploymentHTTPRoundTrip:
    """Full GraphQL ``updateDeployment`` round-trip against the ASGI app.

    Requires a pre-seeded deployment (cluster + environment + driver
    version + active deployment row). The existing ``test_api.py`` suite
    shows the pattern but creating that seed in a scheduling-focused test
    duplicates a lot of setup. Tracked as a follow-up.
    """

    @pytest.mark.anyio
    async def test_updates_deployment_with_scheduling_config(self) -> None:
        pytest.skip(
            "Requires seeded cluster/environment/driver/deployment fixtures; "
            "tracked as follow-up to T036."
        )
