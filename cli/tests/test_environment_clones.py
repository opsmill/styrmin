"""Tests for the env-clones command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk import EnvironmentCloneDeploymentOutcome, EnvironmentCloneStatus
from styrmin_sdk.exceptions import ResourceAlreadyExistsError, ResourceNotFoundError
from styrminctl.cli import app

ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
CREATED_ENV_UUID = "0a1b2c3d-4e5f-6789-abcd-ef0123456789"
CLONE_UUID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
CLUSTER_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
ENV_BACKUP_UUID = "d4e5f6a7-b8c9-0123-def0-123456789abc"
DEPLOYMENT_UUID = "e5f6a7b8-c9d0-1234-ef01-23456789abcd"
COUNTERPART_UUID = "f6a7b8c9-d0e1-2345-f012-3456789abcde"
RESTORE_UUID = "a7b8c9d0-e1f2-3456-0123-456789abcdef"


def _make_deployment_result(
    *,
    deployment_name: str = "demo",
    outcome: EnvironmentCloneDeploymentOutcome = EnvironmentCloneDeploymentOutcome.CLONED,
    reason: str | None = None,
    counterpart_deployment_id: str | None = COUNTERPART_UUID,
    restore_id: str | None = RESTORE_UUID,
) -> MagicMock:
    result = MagicMock(
        deployment_id=DEPLOYMENT_UUID,
        outcome=outcome,
        reason=reason,
        counterpart_deployment_id=counterpart_deployment_id,
        restore_id=restore_id,
    )
    result.deployment_name = deployment_name
    return result


def _make_created_environment(*, name: str = "prod-rehearsal") -> MagicMock:
    created = MagicMock(id=CREATED_ENV_UUID, config={"fqdn_suffix": "rehearsal.local"})
    created.name = name
    return created


def _make_environment_backup() -> MagicMock:
    environment_backup = MagicMock(id=ENV_BACKUP_UUID, status=MagicMock(value="COMPLETED"))
    environment_backup.name = "prod-clone-capture"
    return environment_backup


def _make_environment_clone(
    *,
    status: EnvironmentCloneStatus = EnvironmentCloneStatus.IN_PROGRESS,
    name: str = "prod-rehearsal",
    deployment_results: list[MagicMock] | None = None,
    clone_errors: list[str] | None = None,
    created_environment: MagicMock | None = None,
    source_environment: MagicMock | None = None,
    environment_backup: MagicMock | None = None,
    requested_deployment_ids: list[str] | None = None,
    config_override: dict[str, object] | None = None,
    clear_config_fields: list[str] | None = None,
) -> MagicMock:
    source = MagicMock(id=ENV_UUID) if source_environment is None else source_environment
    environment_clone = MagicMock(
        id=CLONE_UUID,
        status=status,
        source_environment=source,
        source_environment_name="prod",
        environment_backup=_make_environment_backup() if environment_backup is None else environment_backup,
        created_environment=created_environment,
        requested_deployment_ids=requested_deployment_ids,
        config_override=config_override,
        clear_config_fields=clear_config_fields,
        created_on="2026-01-01T00:00:00",
        deployment_results=deployment_results if deployment_results is not None else [_make_deployment_result()],
        clone_errors=clone_errors if clone_errors is not None else [],
    )
    environment_clone.name = name
    return environment_clone


def _seed_environment(mock_client: MagicMock) -> None:
    environment = MagicMock(id=ENV_UUID)
    environment.name = "prod"
    mock_client.environments.get = AsyncMock(return_value=environment)


def test_env_clones_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "get" in output
    assert "list" in output


# --- create ---------------------------------------------------------------


def test_env_clones_create_by_environment_name(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(return_value=_make_environment_clone())

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--name", "prod-rehearsal"])
    assert exc.value.code == 0
    # The name lookup is delegated to the server-side dual-identifier
    # ``environment`` query (ADR-0031) rather than matched in the CLI.
    mock_client.environments.get.assert_called_once_with(
        environment_name="prod", cluster_id=None, cluster_name="default"
    )
    mock_client.environment_clones.create.assert_called_once_with(
        name="prod-rehearsal",
        environment_id=ENV_UUID,
        deployment_ids=None,
        config_override=None,
        clear_config_fields=None,
    )
    output = capsys.readouterr().out
    assert "prod-rehearsal" in output
    assert "IN_PROGRESS" in output
    assert "demo" in output


def test_env_clones_create_by_environment_id(mock_client: MagicMock) -> None:
    mock_client.environment_clones.create = AsyncMock(return_value=_make_environment_clone())

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "--id", ENV_UUID, "--name", "prod-rehearsal"])
    assert exc.value.code == 0
    mock_client.environments.get.assert_not_called()
    assert mock_client.environment_clones.create.call_args.kwargs["environment_id"] == ENV_UUID


def test_env_clones_create_scoped_to_cluster(mock_client: MagicMock) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(return_value=_make_environment_clone())

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--cluster", "edge", "--name", "prod-rehearsal"])
    assert exc.value.code == 0
    mock_client.environments.get.assert_called_once_with(environment_name="prod", cluster_id=None, cluster_name="edge")


def test_env_clones_create_scoped_to_cluster_id(mock_client: MagicMock) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(return_value=_make_environment_clone())

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--cluster-id", CLUSTER_UUID, "--name", "prod-rehearsal"])
    assert exc.value.code == 0
    mock_client.environments.get.assert_called_once_with(
        environment_name="prod", cluster_id=CLUSTER_UUID, cluster_name=None
    )


def test_env_clones_create_rejects_name_and_id(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--id", ENV_UUID, "--name", "prod-rehearsal"])
    assert exc.value.code == 1
    assert "not both" in capsys.readouterr().out
    mock_client.environment_clones.create.assert_not_called()


def test_env_clones_create_requires_a_source(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "--name", "prod-rehearsal"])
    assert exc.value.code == 1
    assert "required" in capsys.readouterr().out
    mock_client.environment_clones.create.assert_not_called()


def test_env_clones_create_rejects_cluster_and_cluster_id(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "env-clones",
                "create",
                "prod",
                "--cluster",
                "edge",
                "--cluster-id",
                CLUSTER_UUID,
                "--name",
                "prod-rehearsal",
            ]
        )
    assert exc.value.code == 1
    assert "not both" in capsys.readouterr().out
    mock_client.environment_clones.create.assert_not_called()


def test_env_clones_create_forwards_selection_and_override_arguments(mock_client: MagicMock) -> None:
    """Wiring check: the selection/override flags reach the SDK (semantics land in T028/T031)."""
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(return_value=_make_environment_clone())

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "env-clones",
                "create",
                "prod",
                "--name",
                "prod-rehearsal",
                "--deployment",
                DEPLOYMENT_UUID,
                "--config-override",
                '{"fqdn_suffix": "rehearsal.local"}',
                "--clear-config-field",
                "ingress_class",
            ]
        )
    assert exc.value.code == 0
    # A UUID needs no lookup, so the deployment list is never fetched.
    mock_client.deployments.list.assert_not_called()
    kwargs = mock_client.environment_clones.create.call_args.kwargs
    assert kwargs["deployment_ids"] == [DEPLOYMENT_UUID]
    assert kwargs["clear_config_fields"] == ["ingress_class"]
    # Sent as a typed UpdateEnvironmentInput; the SDK camelCases it on the wire.
    assert kwargs["config_override"].fqdn_suffix == "rehearsal.local"


def test_env_clones_create_rejects_an_unknown_deployment_name(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name with no match in the source environment fails before the mutation runs."""
    _seed_environment(mock_client)
    known = MagicMock(id=DEPLOYMENT_UUID)
    known.name = "demo"
    mock_client.deployments.list = AsyncMock(return_value=[known])

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--name", "prod-rehearsal", "--deployment", "ghost"])
    assert exc.value.code == 1
    assert "No deployment named 'ghost'" in capsys.readouterr().out
    mock_client.environment_clones.create.assert_not_called()


def test_env_clones_create_exits_non_zero_on_a_terminal_failed_status(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """The status is derived synchronously, so a FAILED clone can come back from the mutation."""
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(
        return_value=_make_environment_clone(
            status=EnvironmentCloneStatus.FAILED,
            deployment_results=[],
            clone_errors=["capture: environment backup FAILED"],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--name", "prod-rehearsal"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "FAILED" in output
    assert "capture: environment backup FAILED" in output
    # Terminal already — nothing is polled.
    mock_client.environment_clones.wait_for_clone.assert_not_called()


def test_env_clones_create_exits_non_zero_on_a_terminal_partial_status(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(
        return_value=_make_environment_clone(
            status=EnvironmentCloneStatus.PARTIAL,
            deployment_results=[
                _make_deployment_result(),
                _make_deployment_result(
                    deployment_name="analytics",
                    outcome=EnvironmentCloneDeploymentOutcome.FAILED,
                    reason="driver_version_gone",
                    counterpart_deployment_id=None,
                    restore_id=None,
                ),
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--name", "prod-rehearsal"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    assert "driver_version_gone" in output


def test_env_clones_create_wait_completed(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(return_value=_make_environment_clone())
    mock_client.environment_clones.wait_for_clone = AsyncMock(
        return_value=_make_environment_clone(
            status=EnvironmentCloneStatus.COMPLETED, created_environment=_make_created_environment()
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--name", "prod-rehearsal", "--wait", "--interval", "0.1"])
    assert exc.value.code == 0
    mock_client.environment_clones.wait_for_clone.assert_called_once_with(CLONE_UUID, max_wait=1800, interval=0.1)
    assert "Environment clone completed" in capsys.readouterr().out


def test_env_clones_create_wait_partial_exits_non_zero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(return_value=_make_environment_clone())
    mock_client.environment_clones.wait_for_clone = AsyncMock(
        return_value=_make_environment_clone(
            status=EnvironmentCloneStatus.PARTIAL,
            deployment_results=[
                _make_deployment_result(
                    deployment_name="analytics",
                    outcome=EnvironmentCloneDeploymentOutcome.SKIPPED,
                    reason="not_eligible",
                    counterpart_deployment_id=None,
                    restore_id=None,
                )
            ],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--name", "prod-rehearsal", "--wait"])
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    assert "not_eligible" in output


def test_env_clones_create_reports_a_taken_target_name(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.create = AsyncMock(
        side_effect=ResourceAlreadyExistsError("Environment 'prod-rehearsal' already exists", "ALREADY_EXISTS")
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "create", "prod", "--name", "prod-rehearsal"])
    assert exc.value.code == 1
    assert "already exists" in capsys.readouterr().out


# --- get ------------------------------------------------------------------


def test_env_clones_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_clones.get = AsyncMock(
        return_value=_make_environment_clone(
            status=EnvironmentCloneStatus.COMPLETED,
            created_environment=_make_created_environment(),
            requested_deployment_ids=[DEPLOYMENT_UUID],
            config_override={"fqdn_suffix": "rehearsal.local"},
            clear_config_fields=["ingress_class"],
        )
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "get", CLONE_UUID])
    assert exc.value.code == 0
    mock_client.environment_clones.get.assert_called_once_with(CLONE_UUID)
    output = capsys.readouterr().out
    assert CLONE_UUID in output
    assert "COMPLETED" in output
    assert "prod" in output
    assert CREATED_ENV_UUID in output
    # The override is stored and rendered as canonical snake_case JSON.
    assert "fqdn_suffix" in output
    assert "ingress_class" in output
    assert "demo" in output


def test_env_clones_get_renders_a_clone_that_outlived_its_inputs(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A terminal clone survives its source environment and its capture."""
    clone = _make_environment_clone(status=EnvironmentCloneStatus.COMPLETED)
    clone.source_environment = None
    clone.environment_backup = None
    mock_client.environment_clones.get = AsyncMock(return_value=clone)

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "get", CLONE_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "source environment deleted" in output
    assert "Environment backup: none" in output
    assert "Created environment: none yet" in output
    assert "all eligible" in output


def test_env_clones_get_not_found(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environment_clones.get = AsyncMock(
        side_effect=ResourceNotFoundError("Environment clone not found", "NOT_FOUND")
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "get", CLONE_UUID])
    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().out


def test_env_clones_get_rejects_a_non_uuid(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "get", "not-a-uuid"])
    assert exc.value.code != 0
    assert "not-a-uuid" in capsys.readouterr().err


# --- list -----------------------------------------------------------------


def test_env_clones_list(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.list = AsyncMock(
        return_value=[
            _make_environment_clone(
                status=EnvironmentCloneStatus.PARTIAL,
                created_environment=_make_created_environment(),
                deployment_results=[
                    _make_deployment_result(),
                    _make_deployment_result(
                        deployment_name="analytics",
                        outcome=EnvironmentCloneDeploymentOutcome.SKIPPED,
                        reason="not_eligible",
                    ),
                ],
            )
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "list", "prod"])
    assert exc.value.code == 0
    mock_client.environment_clones.list.assert_called_once_with(environment_id=ENV_UUID)
    output = capsys.readouterr().out
    assert "PARTIAL" in output
    # cloned/skipped/failed/total
    assert "1/1/0/2" in output


def test_env_clones_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_environment(mock_client)
    mock_client.environment_clones.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "list", "prod"])
    assert exc.value.code == 0
    assert "No environment clones found." in capsys.readouterr().out


def test_env_clones_list_by_environment_id(mock_client: MagicMock) -> None:
    mock_client.environment_clones.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["env-clones", "list", "--id", ENV_UUID])
    assert exc.value.code == 0
    mock_client.environments.get.assert_not_called()
    mock_client.environment_clones.list.assert_called_once_with(environment_id=ENV_UUID)
