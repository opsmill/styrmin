"""Unit tests for EnvironmentCloneResource."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from styrmin_sdk import (
    EnvironmentCloneDeploymentOutcome,
    EnvironmentCloneStatus,
    UpdateEnvironmentInput,
)
from styrmin_sdk.exceptions import OperationFailedError, ResourceAlreadyExistsError, ResourceNotFoundError
from styrmin_sdk.models import EnvVarInput

if TYPE_CHECKING:
    from styrmin_sdk.client import StyrminClient

CLONE_ID = "00000000-0000-0000-0000-0000000000c1"
ENVIRONMENT_ID = "00000000-0000-0000-0000-0000000000e0"
CREATED_ENVIRONMENT_ID = "00000000-0000-0000-0000-0000000000e9"
ENV_BACKUP_ID = "00000000-0000-0000-0000-0000000000e1"
DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000100"
OTHER_DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000101"
COUNTERPART_DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000200"
RESTORE_ID = "00000000-0000-0000-0000-000000000002"
CLUSTER_ID = "00000000-0000-0000-0000-00000000000c"


def _deployment_result(
    *,
    deployment_id: str = DEPLOYMENT_ID,
    deployment_name: str = "demo",
    outcome: str = "CLONED",
    reason: str | None = None,
    counterpart_deployment_id: str | None = COUNTERPART_DEPLOYMENT_ID,
    restore_id: str | None = RESTORE_ID,
) -> dict[str, Any]:
    return {
        "deploymentId": deployment_id,
        "deploymentName": deployment_name,
        "outcome": outcome,
        "reason": reason,
        "counterpartDeploymentId": counterpart_deployment_id,
        "restoreId": restore_id,
    }


def _environment_clone(
    *,
    status: str = "PENDING",
    deployment_results: list[dict[str, Any]] | None = None,
    clone_errors: list[str] | None = None,
    config_override: dict[str, Any] | None = None,
    clear_config_fields: list[str] | None = None,
    requested_deployment_ids: list[str] | None = None,
    created_environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": CLONE_ID,
        "name": "prod-rehearsal",
        "status": status,
        "sourceEnvironmentName": "prod",
        "createdOn": "2026-01-01T00:00:00",
        "updatedOn": None,
        "requestedDeploymentIds": requested_deployment_ids,
        "configOverride": config_override,
        "clearConfigFields": clear_config_fields,
        "cloneErrors": clone_errors if clone_errors is not None else [],
        "sourceEnvironment": {"id": ENVIRONMENT_ID, "name": "prod"},
        "environmentBackup": {"id": ENV_BACKUP_ID, "name": "prod-clone-capture", "status": "COMPLETED"},
        "createdEnvironment": created_environment,
        "deploymentResults": deployment_results if deployment_results is not None else [_deployment_result()],
    }


class TestEnvironmentCloneCreate:
    @staticmethod
    @pytest.mark.asyncio
    async def test_create_by_environment_id(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        environment_clone = await client.environment_clones.create(name="prod-rehearsal", environment_id=ENVIRONMENT_ID)

        assert environment_clone.name == "prod-rehearsal"
        assert environment_clone.status is EnvironmentCloneStatus.PENDING
        assert environment_clone.source_environment_name == "prod"
        assert environment_clone.deployment_results[0].outcome is EnvironmentCloneDeploymentOutcome.CLONED
        query, variables = mock_transport.execute.call_args.args
        assert "cloneEnvironment" in query
        assert variables == {"name": "prod-rehearsal", "environmentId": ENVIRONMENT_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_by_environment_name_scoped_to_cluster(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """The source is addressed by the dual-identifier convention, cluster scoping included."""
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal", environment_name="prod", cluster_name="edge", cluster_id=None
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables == {"name": "prod-rehearsal", "environmentName": "prod", "clusterName": "edge"}

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_omits_unset_optional_arguments(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """Unset selection/override arguments are absent, not sent as explicit nulls."""
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(name="prod-rehearsal", environment_id=ENVIRONMENT_ID)

        _, variables = mock_transport.execute.call_args.args
        assert "deploymentIds" not in variables
        assert "configOverride" not in variables
        assert "clearConfigFields" not in variables

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_sends_selection_and_override(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """configOverride goes out camelCased (UpdateEnvironmentInput), clearConfigFields snake_cased."""
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal",
            environment_id=ENVIRONMENT_ID,
            cluster_id=CLUSTER_ID,
            deployment_ids=[DEPLOYMENT_ID],
            config_override=UpdateEnvironmentInput(fqdn_suffix="rehearsal.local"),
            clear_config_fields=["ingress_class"],
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables == {
            "name": "prod-rehearsal",
            "environmentId": ENVIRONMENT_ID,
            "clusterId": CLUSTER_ID,
            "deploymentIds": [DEPLOYMENT_ID],
            "configOverride": {"fqdnSuffix": "rehearsal.local"},
            "clearConfigFields": ["ingress_class"],
        }

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_sends_every_selected_deployment_id_as_a_string(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """The selection is a list, so all of it travels — and UUIDs are stringified.

        ``deploymentIds`` is ``[UUID!]`` on the wire and the transport JSON-encodes
        the variables, so a ``uuid.UUID`` has to be converted here rather than
        blowing up in the encoder.
        """
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal",
            environment_id=ENVIRONMENT_ID,
            deployment_ids=[UUID(DEPLOYMENT_ID), OTHER_DEPLOYMENT_ID],
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables["deploymentIds"] == [DEPLOYMENT_ID, OTHER_DEPLOYMENT_ID]

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_sends_an_explicit_empty_selection(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """``[]`` is a selection that selects nothing — not the same as omitting it.

        ``None`` means "every eligible deployment" (FR-003), so an empty list must
        reach the server as an empty list rather than being dropped like an unset
        argument.
        """
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(name="prod-rehearsal", environment_id=ENVIRONMENT_ID, deployment_ids=[])

        _, variables = mock_transport.execute.call_args.args
        assert variables["deploymentIds"] == []

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_unknown_selected_deployment(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """A selected id the source does not have is refused upfront as NOT_FOUND.

        Distinct from a selected-but-ineligible deployment, which is *not* an
        error: it comes back as a ``SKIPPED`` entry with a reason (FR-004), which
        is what ``test_create_is_in_progress_when_a_skip_was_recorded_upfront``
        covers.
        """
        mock_transport.execute.return_value = {
            "data": None,
            "errors": [
                {
                    "message": "These deployments do not exist in the source environment: " + OTHER_DEPLOYMENT_ID,
                    "extensions": {"code": "NOT_FOUND", "deployment_ids": [OTHER_DEPLOYMENT_ID]},
                }
            ],
        }

        with pytest.raises(ResourceNotFoundError):
            await client.environment_clones.create(
                name="prod-rehearsal",
                environment_id=ENVIRONMENT_ID,
                deployment_ids=[DEPLOYMENT_ID, OTHER_DEPLOYMENT_ID],
            )

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_returns_snake_case_config_override(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """The override is sent camelCase but stored and returned as canonical snake_case JSON."""
        mock_transport.execute.return_value = {
            "data": {
                "cloneEnvironment": _environment_clone(
                    config_override={"fqdn_suffix": "rehearsal.local"},
                    clear_config_fields=["ingress_class"],
                )
            }
        }

        environment_clone = await client.environment_clones.create(
            name="prod-rehearsal",
            environment_id=ENVIRONMENT_ID,
            config_override=UpdateEnvironmentInput(fqdn_suffix="rehearsal.local"),
            clear_config_fields=["ingress_class"],
        )

        assert environment_clone.config_override == {"fqdn_suffix": "rehearsal.local"}
        assert environment_clone.clear_config_fields == ["ingress_class"]

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_sends_a_multi_field_override_with_only_the_set_fields(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """A partial override travels as a partial input, list fields included.

        ``UpdateEnvironmentInput`` has a field per environment-config key, all
        optional, so a caller who sets two of them must not accidentally send
        the other nine as explicit nulls — on the server every present field
        *replaces* the captured one wholesale (research D7), so a stray null
        would silently wipe a captured setting the operator never mentioned.
        ``env_vars`` is included because it is the one list-shaped field, sent
        as ``[{name, value}]`` rather than a map.
        """
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal",
            environment_id=ENVIRONMENT_ID,
            config_override=UpdateEnvironmentInput(
                fqdn_suffix="rehearsal.local",
                env_vars=[EnvVarInput(name="SMTP_HOST", value="localhost")],
            ),
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables["configOverride"] == {
            "fqdnSuffix": "rehearsal.local",
            "envVars": [{"name": "SMTP_HOST", "value": "localhost"}],
        }

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_accepts_an_override_built_from_camel_case_keys(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """``UpdateEnvironmentInput`` populates by name *or* alias.

        This is what lets the CLI hand raw JSON straight to
        ``model_validate`` and accept whichever casing the operator typed; the
        wire form is camelCase either way.
        """
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal",
            environment_id=ENVIRONMENT_ID,
            config_override=UpdateEnvironmentInput.model_validate({"fqdnSuffix": "rehearsal.local"}),
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables["configOverride"] == {"fqdnSuffix": "rehearsal.local"}

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_sends_an_explicit_empty_clear_config_fields(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """``[]`` clears nothing but is still a request the server may see.

        Same reasoning as the empty deployment selection: the resource
        distinguishes "not supplied" from "supplied empty" by presence, so an
        empty list must not be dropped like an unset argument.
        """
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal", environment_id=ENVIRONMENT_ID, clear_config_fields=[]
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables["clearConfigFields"] == []

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_sends_every_clear_config_field_in_order(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """Multiple fields can be cleared in one clone, snake_case throughout.

        ``clearConfigFields`` names ``EnvironmentConfig`` fields, not
        ``UpdateEnvironmentInput`` ones, so — unlike ``configOverride`` — the
        names are **not** camelCased on the way out.
        """
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal",
            environment_id=ENVIRONMENT_ID,
            clear_config_fields=("ingress_class", "external_dns_endpoints_type"),
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables["clearConfigFields"] == ["ingress_class", "external_dns_endpoints_type"]

    @staticmethod
    def test_override_rejects_a_wrongly_typed_value_client_side() -> None:
        """A value of the wrong type is refused before any request is built."""
        with pytest.raises(ValidationError):
            UpdateEnvironmentInput.model_validate({"externalUrlPort": "not-a-port"})

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_drops_an_unknown_override_key_client_side(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """**Known gap**, characterised here rather than left undiscovered.

        The ariadne-codegen base model does not set ``extra="forbid"``, so
        ``UpdateEnvironmentInput`` *ignores* an unrecognised key instead of
        raising. The misspelled field therefore never reaches the server's
        ``extra="forbid"`` ``EnvironmentConfig`` validation and the override
        silently degrades to a no-op. The same model backs the CLI's
        ``--config-override`` parsing, so for US3 a typo means a clone that
        quietly keeps production configuration — worth fixing, and worth being
        visible until it is.
        """
        mock_transport.execute.return_value = {"data": {"cloneEnvironment": _environment_clone()}}

        await client.environment_clones.create(
            name="prod-rehearsal",
            environment_id=ENVIRONMENT_ID,
            config_override=UpdateEnvironmentInput.model_validate({"fqdnSufix": "typo.local"}),
        )

        _, variables = mock_transport.execute.call_args.args
        assert variables["configOverride"] == {}

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_is_in_progress_when_a_skip_was_recorded_upfront(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """A just-registered clone can already be IN_PROGRESS — never assume a PENDING first read."""
        mock_transport.execute.return_value = {
            "data": {
                "cloneEnvironment": _environment_clone(
                    status="IN_PROGRESS",
                    deployment_results=[
                        _deployment_result(),
                        _deployment_result(
                            deployment_id=OTHER_DEPLOYMENT_ID,
                            deployment_name="analytics",
                            outcome="SKIPPED",
                            reason="not_eligible",
                            counterpart_deployment_id=None,
                            restore_id=None,
                        ),
                    ],
                )
            }
        }

        environment_clone = await client.environment_clones.create(name="prod-rehearsal", environment_id=ENVIRONMENT_ID)

        assert environment_clone.status is EnvironmentCloneStatus.IN_PROGRESS
        skipped = environment_clone.deployment_results[1]
        assert skipped.outcome is EnvironmentCloneDeploymentOutcome.SKIPPED
        assert skipped.reason == "not_eligible"
        assert skipped.counterpart_deployment_id is None

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_target_name_taken(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": None,
            "errors": [
                {
                    "message": "Environment 'prod-rehearsal' already exists",
                    "extensions": {"code": "ALREADY_EXISTS"},
                }
            ],
        }

        with pytest.raises(ResourceAlreadyExistsError):
            await client.environment_clones.create(name="prod-rehearsal", environment_id=ENVIRONMENT_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_unknown_source(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": None,
            "errors": [{"message": "Environment not found", "extensions": {"code": "NOT_FOUND"}}],
        }

        with pytest.raises(ResourceNotFoundError):
            await client.environment_clones.create(name="prod-rehearsal", environment_name="nope")

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_invalid_clear_config_field(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": None,
            "errors": [
                {
                    "message": "'nope' is not an environment config field",
                    "extensions": {"code": "VALIDATION_ERROR"},
                }
            ],
        }

        with pytest.raises(OperationFailedError):
            await client.environment_clones.create(
                name="prod-rehearsal", environment_id=ENVIRONMENT_ID, clear_config_fields=["nope"]
            )

    @staticmethod
    @pytest.mark.asyncio
    async def test_create_already_in_progress(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": None,
            "errors": [
                {
                    "message": "An environment operation is already in progress",
                    "extensions": {"code": "ALREADY_IN_PROGRESS"},
                }
            ],
        }

        with pytest.raises(OperationFailedError):
            await client.environment_clones.create(name="prod-rehearsal", environment_id=ENVIRONMENT_ID)


class TestEnvironmentCloneReads:
    @staticmethod
    @pytest.mark.asyncio
    async def test_get(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "environmentClone": _environment_clone(
                    status="COMPLETED",
                    created_environment={
                        "id": CREATED_ENVIRONMENT_ID,
                        "name": "prod-rehearsal",
                        "config": {"fqdn_suffix": "rehearsal.local"},
                    },
                )
            }
        }

        environment_clone = await client.environment_clones.get(CLONE_ID)

        assert environment_clone.status is EnvironmentCloneStatus.COMPLETED
        assert environment_clone.created_environment is not None
        assert str(environment_clone.created_environment.id) == CREATED_ENVIRONMENT_ID
        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentCloneId": CLONE_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_not_found_raises_rather_than_returning_none(
        client: StyrminClient, mock_transport: AsyncMock
    ) -> None:
        """``environmentClone`` is non-null: an unknown id is an error, not a null."""
        mock_transport.execute.return_value = {
            "data": None,
            "errors": [{"message": "Environment clone not found", "extensions": {"code": "NOT_FOUND"}}],
        }

        with pytest.raises(ResourceNotFoundError):
            await client.environment_clones.get(CLONE_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_projects_flattened_clone_errors(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """Operation-level events arrive as flat ``"step: error"`` strings, not structured objects."""
        mock_transport.execute.return_value = {
            "data": {
                "environmentClone": _environment_clone(
                    status="FAILED",
                    deployment_results=[],
                    clone_errors=["capture: environment backup FAILED"],
                )
            }
        }

        environment_clone = await client.environment_clones.get(CLONE_ID)

        assert environment_clone.status is EnvironmentCloneStatus.FAILED
        assert environment_clone.clone_errors == ["capture: environment backup FAILED"]
        assert environment_clone.created_environment is None

    @staticmethod
    @pytest.mark.asyncio
    async def test_get_tolerates_a_deleted_source_and_capture(client: StyrminClient, mock_transport: AsyncMock) -> None:
        """A terminal clone survives its source environment and its capture."""
        payload = _environment_clone(status="COMPLETED")
        payload["sourceEnvironment"] = None
        payload["environmentBackup"] = None
        mock_transport.execute.return_value = {"data": {"environmentClone": payload}}

        environment_clone = await client.environment_clones.get(CLONE_ID)

        assert environment_clone.source_environment is None
        assert environment_clone.environment_backup is None
        assert environment_clone.source_environment_name == "prod"

    @staticmethod
    @pytest.mark.asyncio
    async def test_list(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {
            "data": {
                "environmentClones": [
                    {
                        "id": CLONE_ID,
                        "name": "prod-rehearsal",
                        "status": "PARTIAL",
                        "sourceEnvironmentName": "prod",
                        "createdOn": "2026-01-01T00:00:00",
                        "updatedOn": None,
                        "cloneErrors": [],
                        "createdEnvironment": {"id": CREATED_ENVIRONMENT_ID, "name": "prod-rehearsal"},
                        "deploymentResults": [
                            {
                                "deploymentId": DEPLOYMENT_ID,
                                "deploymentName": "demo",
                                "outcome": "CLONED",
                                "reason": None,
                            },
                            {
                                "deploymentId": OTHER_DEPLOYMENT_ID,
                                "deploymentName": "analytics",
                                "outcome": "FAILED",
                                "reason": "driver_version_gone",
                            },
                        ],
                    }
                ]
            }
        }

        environment_clones = await client.environment_clones.list(environment_id=ENVIRONMENT_ID)

        assert len(environment_clones) == 1
        assert environment_clones[0].status is EnvironmentCloneStatus.PARTIAL
        assert environment_clones[0].deployment_results[1].reason == "driver_version_gone"
        _, variables = mock_transport.execute.call_args.args
        assert variables == {"environmentId": ENVIRONMENT_ID}

    @staticmethod
    @pytest.mark.asyncio
    async def test_list_empty(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"environmentClones": []}}

        assert await client.environment_clones.list(environment_id=ENVIRONMENT_ID) == []


class TestWaitForClone:
    @staticmethod
    @pytest.mark.asyncio
    async def test_polls_until_terminal(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.side_effect = [
            {"data": {"environmentClone": _environment_clone(status="IN_PROGRESS")}},
            {"data": {"environmentClone": _environment_clone(status="COMPLETED")}},
        ]

        environment_clone = await client.environment_clones.wait_for_clone(CLONE_ID, max_wait=10, interval=0)

        assert environment_clone.status is EnvironmentCloneStatus.COMPLETED
        assert mock_transport.execute.await_count == 2

    @staticmethod
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["COMPLETED", "PARTIAL", "FAILED"])
    async def test_treats_partial_and_failed_as_terminal(
        client: StyrminClient, mock_transport: AsyncMock, status: str
    ) -> None:
        """COMPLETED / PARTIAL / FAILED are all final — polling must stop on each."""
        mock_transport.execute.return_value = {"data": {"environmentClone": _environment_clone(status=status)}}

        environment_clone = await client.environment_clones.wait_for_clone(CLONE_ID, max_wait=10, interval=0)

        assert environment_clone.status is EnvironmentCloneStatus(status)
        assert mock_transport.execute.await_count == 1

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_stop_on_pending_or_in_progress(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.side_effect = [
            {"data": {"environmentClone": _environment_clone(status="PENDING")}},
            {"data": {"environmentClone": _environment_clone(status="IN_PROGRESS")}},
            {"data": {"environmentClone": _environment_clone(status="PARTIAL")}},
        ]

        environment_clone = await client.environment_clones.wait_for_clone(CLONE_ID, max_wait=10, interval=0)

        assert environment_clone.status is EnvironmentCloneStatus.PARTIAL
        assert mock_transport.execute.await_count == 3

    @staticmethod
    @pytest.mark.asyncio
    async def test_returns_last_record_on_timeout(client: StyrminClient, mock_transport: AsyncMock) -> None:
        mock_transport.execute.return_value = {"data": {"environmentClone": _environment_clone(status="IN_PROGRESS")}}

        environment_clone = await client.environment_clones.wait_for_clone(CLONE_ID, max_wait=0, interval=0)

        assert environment_clone.status is EnvironmentCloneStatus.IN_PROGRESS
