"""Unit tests for the errors raised for deployment references in affinity terms."""

from __future__ import annotations

from uuid import UUID

from styrmin_backend.context import exceptions as context_exceptions
from styrmin_backend.services.exceptions import (
    UnclonedDeploymentReferenceError,
    UnclonedReference,
    UnresolvableAffinityReferenceError,
)

_POSTGRES_ID = "7f0c2a3e-1b2c-4d5e-8f90-0a1b2c3d4e5f"
_REDIS_ID = "1d2e3f40-5a6b-4c7d-8e9f-a0b1c2d3e4f5"
_PATH = "deployment.config.scheduling.pod_affinity.required[0]"


class TestUnresolvableAffinityReferenceError:
    def test_missing_name_without_deleted(self) -> None:
        err = UnresolvableAffinityReferenceError(deployment_name="postgres", path=_PATH)

        assert err.error_code == "VALIDATION_ERROR"
        assert err.deleted is False
        assert str(err) == "Affinity deployment reference cannot be resolved: postgres"
        assert err.error_metadata == {"deployment_name": "postgres", "path": _PATH}

    def test_missing_id_without_deleted_has_no_deleted_key(self) -> None:
        err = UnresolvableAffinityReferenceError(deployment_id=_POSTGRES_ID, path=_PATH)

        assert (
            str(err)
            == f"Affinity deployment reference cannot be resolved: {_POSTGRES_ID}"
        )
        assert "deleted" not in err.error_metadata
        assert err.error_metadata == {"deployment_id": _POSTGRES_ID, "path": _PATH}

    def test_tombstoned_deployment_gives_last_name_and_deleted(self) -> None:
        err = UnresolvableAffinityReferenceError(
            deployment_id=_POSTGRES_ID,
            deployment_name="postgres",
            path=_PATH,
            deleted=True,
        )

        assert err.error_code == "VALIDATION_ERROR"
        assert str(err) == (
            f"Affinity term at {_PATH} names deployment 'postgres' ({_POSTGRES_ID}), which was deleted"
        )
        assert err.error_metadata == {
            "deployment_id": _POSTGRES_ID,
            "deployment_name": "postgres",
            "path": _PATH,
            "deleted": True,
        }

    def test_explicit_message_wins(self) -> None:
        err = UnresolvableAffinityReferenceError(
            "custom", deployment_id=_POSTGRES_ID, deleted=True
        )

        assert str(err) == "custom"
        assert err.error_metadata["deleted"] is True


class TestUnclonedDeploymentReferenceError:
    def test_metadata_lists_each_deployment_with_its_paths(self) -> None:
        err = UnclonedDeploymentReferenceError(
            [
                UnclonedReference(
                    deployment_id=UUID(_POSTGRES_ID),
                    deployment_name="postgres",
                    paths=[
                        "environment.config.scheduling.pod_anti_affinity.preferred[0].term",
                        "deployment[api].config.scheduling.pod_affinity.required[0]",
                    ],
                ),
                UnclonedReference(
                    deployment_id=UUID(_REDIS_ID),
                    deployment_name="redis",
                    paths=[
                        "deployment[api].config.scheduling.pod_affinity.required[1]",
                        "deployment[api].component[server].config.scheduling.pod_affinity.required[0]",
                    ],
                ),
            ]
        )

        assert err.error_code == "VALIDATION_ERROR"
        assert str(err) == (
            "An affinity term names a deployment that the clone does not copy: postgres, redis"
        )
        assert err.error_metadata == {
            "deployments": [
                {
                    "deployment_id": _POSTGRES_ID,
                    "deployment_name": "postgres",
                    "paths": [
                        "environment.config.scheduling.pod_anti_affinity.preferred[0].term",
                        "deployment[api].config.scheduling.pod_affinity.required[0]",
                    ],
                },
                {
                    "deployment_id": _REDIS_ID,
                    "deployment_name": "redis",
                    "paths": [
                        "deployment[api].config.scheduling.pod_affinity.required[1]",
                        "deployment[api].component[server].config.scheduling.pod_affinity.required[0]",
                    ],
                },
            ]
        }

    def test_message_falls_back_to_id_without_name(self) -> None:
        err = UnclonedDeploymentReferenceError(
            [
                UnclonedReference(
                    deployment_id=UUID(_POSTGRES_ID),
                    deployment_name=None,
                    paths=[_PATH],
                )
            ]
        )

        assert (
            str(err)
            == f"An affinity term names a deployment that the clone does not copy: {_POSTGRES_ID}"
        )
        assert err.error_metadata["deployments"][0]["deployment_name"] is None

    def test_reexported_from_context_exceptions(self) -> None:
        assert (
            context_exceptions.UnclonedDeploymentReferenceError
            is UnclonedDeploymentReferenceError
        )
        assert (
            context_exceptions.UnresolvableAffinityReferenceError
            is UnresolvableAffinityReferenceError
        )
