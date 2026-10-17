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


_ENV_PATH = "environment.config.scheduling.pod_anti_affinity.preferred[0].term"
_COMPONENT_PATH = "component[server].config.scheduling.pod_affinity.required[0]"


class TestUnresolvableAffinityReferenceError:
    def test_missing_name_gives_path_and_environment(self) -> None:
        err = UnresolvableAffinityReferenceError(
            deployment_name="postgres", path=_PATH, environment_name="prod"
        )

        assert err.error_code == "VALIDATION_ERROR"
        assert err.deleted is False
        assert str(err) == (
            f"Affinity term at {_PATH} names deployment 'postgres', "
            "which is not a deployment of environment 'prod'."
        )
        assert err.error_metadata == {"deployment_name": "postgres", "path": _PATH}

    def test_missing_id_without_deleted_has_no_deleted_key(self) -> None:
        err = UnresolvableAffinityReferenceError(
            deployment_id=_POSTGRES_ID, path=_PATH, environment_name="prod"
        )

        assert str(err) == (
            f"Affinity term at {_PATH} names deployment id {_POSTGRES_ID}, "
            "which is not a deployment of environment 'prod'."
        )
        assert "deleted" not in err.error_metadata
        assert err.error_metadata == {"deployment_id": _POSTGRES_ID, "path": _PATH}

    def test_new_environment_says_why_and_how_to_add_the_term(self) -> None:
        err = UnresolvableAffinityReferenceError(
            deployment_name="postgres", path=_ENV_PATH, new_environment=True
        )

        assert str(err) == (
            f"Affinity term at {_ENV_PATH} names deployment 'postgres', but a new "
            "environment has no deployments yet. Add the term with updateEnvironment "
            "once the deployment exists."
        )

    def test_tombstoned_deployment_in_a_deployment_config(self) -> None:
        err = UnresolvableAffinityReferenceError(
            deployment_id=_POSTGRES_ID,
            deployment_name="postgres",
            path=_PATH,
            deleted=True,
        )

        assert err.error_code == "VALIDATION_ERROR"
        assert str(err) == (
            f"Affinity term at {_PATH} names deployment 'postgres' ({_POSTGRES_ID}), "
            "which was deleted. To fix it, change or remove the term in the "
            "deployment's config."
        )
        assert err.error_metadata == {
            "deployment_id": _POSTGRES_ID,
            "deployment_name": "postgres",
            "path": _PATH,
            "deleted": True,
        }

    def test_tombstoned_deployment_in_the_environment_config_names_the_role(
        self,
    ) -> None:
        err = UnresolvableAffinityReferenceError(
            deployment_id=_POSTGRES_ID,
            deployment_name="postgres",
            path=_ENV_PATH,
            deleted=True,
        )

        assert str(err) == (
            f"Affinity term at {_ENV_PATH} names deployment 'postgres' ({_POSTGRES_ID}), "
            "which was deleted. To fix it, change or remove the term in the "
            "environment's config with updateEnvironment, which needs the ADMIN role, "
            "or discard the environment's terms of this kind in the deployment's "
            "config with replace: true."
        )

    def test_tombstoned_deployment_in_a_component_config_names_the_driver_version(
        self,
    ) -> None:
        err = UnresolvableAffinityReferenceError(
            deployment_id=_POSTGRES_ID,
            deployment_name="postgres",
            path=_COMPONENT_PATH,
            deleted=True,
        )

        assert str(err).endswith(
            "which was deleted. The term comes from the component definitions of the "
            "deployment's driver version. To fix it, move the deployment to a driver "
            "version whose definitions do not name the deleted deployment."
        )

    def test_explicit_message_wins(self) -> None:
        err = UnresolvableAffinityReferenceError(
            "custom", deployment_id=_POSTGRES_ID, deleted=True
        )

        assert str(err) == "custom"
        assert err.error_metadata["deleted"] is True


class TestUnclonedDeploymentReferenceError:
    def test_message_and_metadata_list_each_deployment_with_its_reason_and_paths(
        self,
    ) -> None:
        err = UnclonedDeploymentReferenceError(
            [
                UnclonedReference(
                    deployment_id=UUID(_POSTGRES_ID),
                    deployment_name="postgres",
                    paths=[
                        "environment.config.scheduling.pod_anti_affinity.preferred[0].term",
                        "deployment[api].config.scheduling.pod_affinity.required[0]",
                    ],
                    reason="not included in the requested deployment selection",
                ),
                UnclonedReference(
                    deployment_id=UUID(_REDIS_ID),
                    deployment_name="redis",
                    paths=[
                        "deployment[api].component[server].config.scheduling.pod_affinity.required[0]",
                    ],
                ),
            ],
            with_fixes=True,
        )

        assert err.error_code == "VALIDATION_ERROR"
        assert str(err) == (
            "An affinity term names a deployment that the clone does not copy: "
            "'postgres' (not included in the requested deployment selection), named at "
            "environment.config.scheduling.pod_anti_affinity.preferred[0].term, "
            "deployment[api].config.scheduling.pod_affinity.required[0]; "
            "'redis', named at "
            "deployment[api].component[server].config.scheduling.pod_affinity.required[0]. "
            "Add the deployment to the selection, leave out the deployments whose terms "
            "name it, or, for a term in the environment's config, clear scheduling or "
            "override it with a scheduling that names no deployment."
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
                    "reason": "not included in the requested deployment selection",
                },
                {
                    "deployment_id": _REDIS_ID,
                    "deployment_name": "redis",
                    "paths": [
                        "deployment[api].component[server].config.scheduling.pod_affinity.required[0]",
                    ],
                    "reason": None,
                },
            ]
        }

    def test_message_falls_back_to_id_without_name_and_has_no_fixes_by_default(
        self,
    ) -> None:
        err = UnclonedDeploymentReferenceError(
            [
                UnclonedReference(
                    deployment_id=UUID(_POSTGRES_ID),
                    deployment_name=None,
                    paths=[_PATH],
                )
            ]
        )

        assert str(err) == (
            "An affinity term names a deployment that the clone does not copy: "
            f"{_POSTGRES_ID}, named at {_PATH}."
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
