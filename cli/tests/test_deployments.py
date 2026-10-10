"""Tests for the deployments command group."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from styrmin_sdk.exceptions import ApplyError, BatchNameConflictError, StyrminError
from styrmin_sdk.models import UpdateDeploymentInput
from styrmin_sdk.models.deployment_manifest import ApplyOutcome
from styrminctl.cli import app

DEPLOYMENT_UUID = "a7b8c9d0-e1f2-3456-0123-456789abcdef"
ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
TASK_UUID = "f1e2d3c4-b5a6-9870-abcd-1234567890ab"


def test_deployments_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["deployments", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "get" in output
    assert "update" in output
    assert "update-version" in output
    assert "start-components" in output
    assert "stop-components" in output
    assert "run-job" in output
    assert "context" in output


def test_deployments_create(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", deployment_id=DEPLOYMENT_UUID, status="pending")
    mock_client.deployments.create = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "create", "postgres", "14.0", "--id", ENV_UUID])
    assert exc.value.code == 0
    mock_client.deployments.create.assert_called_once_with(
        driver="postgres",
        version="14.0",
        environment_id=ENV_UUID,
        environment_name=None,
        cluster_id=None,
        cluster_name=None,
        name=None,
        config=None,
        driver_version_id=None,
    )
    output = capsys.readouterr().out
    assert DEPLOYMENT_UUID in output


def test_deployments_create_with_options(mock_client: MagicMock) -> None:
    mock_task = MagicMock(id="t-1", deployment_id=DEPLOYMENT_UUID, status="pending")
    mock_client.deployments.create = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "deployments",
                "create",
                "postgres",
                "14.0",
                "--id",
                ENV_UUID,
                "--name",
                "my-db",
                "--config",
                '{"key": "val"}',
            ]
        )
    assert exc.value.code == 0
    mock_client.deployments.create.assert_called_once_with(
        driver="postgres",
        version="14.0",
        environment_id=ENV_UUID,
        environment_name=None,
        cluster_id=None,
        cluster_name=None,
        name="my-db",
        config={"key": "val"},
        driver_version_id=None,
    )


def test_deployments_create_with_driver_version_pin(mock_client: MagicMock) -> None:
    mock_task = MagicMock(id="t-1", deployment_id=DEPLOYMENT_UUID, status="pending")
    mock_client.deployments.create = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "create", "postgres", "14.0", ENV_UUID, "--driver-version-id", "dv-1"])
    assert exc.value.code == 0
    mock_client.deployments.create.assert_called_once_with(
        driver="postgres",
        version="14.0",
        environment_id=None,
        environment_name=ENV_UUID,
        cluster_id=None,
        cluster_name="default",
        name=None,
        config=None,
        driver_version_id="dv-1",
    )


def test_deployments_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_deployment = MagicMock(
        id=DEPLOYMENT_UUID,
        name="my-db",
        status="running",
        application_version="14.0",
        application_driver_version_id="dv-1",
        environment_id=ENV_UUID,
        config=None,
        application_instance=None,
        components=[],
    )
    mock_client.deployments.get = AsyncMock(return_value=mock_deployment)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "get", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.deployments.get.assert_called_once_with(DEPLOYMENT_UUID)
    output = capsys.readouterr().out
    assert DEPLOYMENT_UUID in output


def test_deployments_update(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.update = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "update", DEPLOYMENT_UUID, "--config", '{"name": "renamed-db"}'])
    assert exc.value.code == 0
    mock_client.deployments.update.assert_called_once_with(
        DEPLOYMENT_UUID, input=UpdateDeploymentInput(name="renamed-db")
    )
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_update_version(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.update_version = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "update-version", DEPLOYMENT_UUID, "15.0"])
    assert exc.value.code == 0
    mock_client.deployments.update_version.assert_called_once_with(
        DEPLOYMENT_UUID, version="15.0", driver_version_id=None, input=None
    )
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_update_version_with_config(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    """``--config`` is written with the version, so it is checked against the target driver version."""
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.update_version = AsyncMock(return_value=mock_task)
    config = '{"components": [{"name": "server", "envVars": [{"name": "LOG_LEVEL", "value": "debug"}]}]}'

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "update-version", DEPLOYMENT_UUID, "15.0", "--config", config])
    assert exc.value.code == 0
    mock_client.deployments.update_version.assert_called_once_with(
        DEPLOYMENT_UUID,
        version="15.0",
        driver_version_id=None,
        input=UpdateDeploymentInput.model_validate(
            {"components": [{"name": "server", "envVars": [{"name": "LOG_LEVEL", "value": "debug"}]}]}
        ),
    )
    assert "t-1" in capsys.readouterr().out


def test_deployments_update_version_with_driver_version_pin(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.update_version = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "update-version", DEPLOYMENT_UUID, "15.0", "--driver-version-id", "dv-2"])
    assert exc.value.code == 0
    mock_client.deployments.update_version.assert_called_once_with(
        DEPLOYMENT_UUID, version="15.0", driver_version_id="dv-2", input=None
    )
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_start_components(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.start_components = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "start-components", DEPLOYMENT_UUID, "--component", "web", "--component", "worker"])
    assert exc.value.code == 0
    mock_client.deployments.start_components.assert_called_once_with(DEPLOYMENT_UUID, components=["web", "worker"])
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_stop_components(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.stop_components = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "stop-components", DEPLOYMENT_UUID, "--component", "worker"])
    assert exc.value.code == 0
    mock_client.deployments.stop_components.assert_called_once_with(DEPLOYMENT_UUID, components=["worker"])


def test_deployments_run_job(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.run_job = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "deployments",
                "run-job",
                DEPLOYMENT_UUID,
                "--image",
                "postgres:14",
                "--command",
                "pg_dump",
                "--command",
                "localhost",
                "--env",
                '{"PG_PASSWORD": "secret"}',
            ]
        )
    assert exc.value.code == 0
    mock_client.deployments.run_job.assert_called_once()
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_context(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_ctx = MagicMock(context={"namespace": "prod", "cluster": "main"})
    mock_client.deployments.get_context = AsyncMock(return_value=mock_ctx)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "context", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.deployments.get_context.assert_called_once_with(DEPLOYMENT_UUID)


def test_deployments_create_error(mock_client: MagicMock) -> None:
    mock_client.deployments.create = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "create", "postgres", "14.0", ENV_UUID])
    assert exc.value.code == 1


def test_deployments_get_renders_driver_version_label_with_short_suffix(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec 013 / US4: deployment detail renders the driver-version reference as <version>@<short>
    and emits a full Content hash line when the underlying row is a local driver."""
    full_hash = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
    adv = MagicMock(version="14.0", content_hash=full_hash, source_commit_sha=None)
    mock_deployment = MagicMock(
        id=DEPLOYMENT_UUID,
        name="my-db",
        status="running",
        application_version="14.0",
        application_driver_version_id="dv-1",
        application_driver_version=adv,
        environment_id=ENV_UUID,
        config=None,
        application_instance=None,
        components=[],
    )
    mock_client.deployments.get = AsyncMock(return_value=mock_deployment)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "get", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Application version: 14.0@a1b2c3d" in output
    assert f"Content hash: {full_hash}" in output
    assert "Commit SHA:" not in output


# --------------------------------------------------------------------------
# `deployments apply` — delegates to `apply_files` (chunks 6 + 9).
# --------------------------------------------------------------------------


_VALID_MANIFEST = """\
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-app
spec:
  driver: acme/web
  version: "1.2.3"
  environment: prod
"""


def _write_manifest(tmp_path: Path, body: str, *, filename: str = "manifest.yaml") -> Path:
    path = tmp_path / filename
    path.write_text(body, encoding="utf-8")
    return path


def _outcome(
    name: str,
    action: Literal["created", "updated", "failed"],
    *,
    reason: str | None = None,
) -> ApplyOutcome:
    if action == "failed":
        return ApplyOutcome(name=name, action="failed", failure_reason=reason or "boom")
    return ApplyOutcome(
        name=name,
        action=action,
        deployment_id=UUID(DEPLOYMENT_UUID),
        task_id=UUID(TASK_UUID),
    )


def test_deployments_apply_create_success(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(return_value=[_outcome("my-app", "created")])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0

    mock_client.deployments.apply_files.assert_awaited_once()
    output = capsys.readouterr().out
    assert "created my-app" in output
    assert "1 created, 0 updated, 0 unchanged, 0 failed" in output


def test_deployments_apply_update_success(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(return_value=[_outcome("my-app", "updated")])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert "updated my-app" in output
    assert "0 created, 1 updated, 0 unchanged, 0 failed" in output


def test_deployments_apply_failed_outcome_exits_one(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A single failed outcome surfaces as `failed <name>: <reason>` + exit 1."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(
        return_value=[
            _outcome(
                "my-app",
                "failed",
                reason="driver mismatch (manifest='acme/web', existing='other/db')",
            )
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    assert "failed my-app: driver mismatch" in output
    assert "0 created, 0 updated, 0 unchanged, 1 failed" in output


def test_deployments_apply_directory_mixed_outcomes(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Three valid + one invalid in a directory → 3 success lines + 1 fail line + exit 1."""
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    for n in ("a", "b", "c", "d"):
        _write_manifest(manifests_dir, _VALID_MANIFEST, filename=f"{n}.yaml")

    mock_client.deployments.apply_files = AsyncMock(
        return_value=[
            _outcome("alpha", "created"),
            _outcome("beta", "updated"),
            _outcome("gamma", "created"),
            _outcome("delta", "failed", reason="environment 'prod' not found"),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifests_dir)])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    assert "created alpha" in output
    assert "updated beta" in output
    assert "created gamma" in output
    assert "failed delta: environment 'prod' not found" in output
    assert "2 created, 1 updated, 0 unchanged, 1 failed" in output


def test_deployments_apply_multi_doc_one_invalid(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Multi-doc YAML where one doc is invalid: other docs still proceed."""
    multi_doc = _VALID_MANIFEST + "---\n" + _VALID_MANIFEST + "---\nnot: a manifest\n"
    manifest = _write_manifest(tmp_path, multi_doc)
    mock_client.deployments.apply_files = AsyncMock(
        return_value=[
            _outcome("my-app", "created"),
            _outcome("my-app", "updated"),
            _outcome(
                "manifest",
                "failed",
                reason="manifest manifest.yaml: document 2: 1 validation error...",
            ),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    assert "created my-app" in output
    assert "updated my-app" in output
    assert "failed manifest:" in output
    assert "1 created, 1 updated, 0 unchanged, 1 failed" in output


def test_deployments_apply_multiple_f_flags(
    mock_client: MagicMock,
    tmp_path: Path,
) -> None:
    """Multiple `-f` flags forward every path to `apply_files`."""
    a = _write_manifest(tmp_path, _VALID_MANIFEST, filename="a.yaml")
    b = _write_manifest(tmp_path, _VALID_MANIFEST, filename="b.yaml")
    mock_client.deployments.apply_files = AsyncMock(
        return_value=[_outcome("alpha", "created"), _outcome("beta", "updated")]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(a), "-f", str(b)])
    assert exc.value.code == 0

    mock_client.deployments.apply_files.assert_awaited_once()
    args, _kwargs = mock_client.deployments.apply_files.call_args
    paths = args[0]
    assert [Path(p) for p in paths] == [a, b]


def test_deployments_apply_name_with_two_manifests(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--name` + multi-manifest input → exit 1 with the SDK's conflict message."""
    monkeypatch.delenv("STYRMIN_NAME", raising=False)
    a = _write_manifest(tmp_path, _VALID_MANIFEST, filename="a.yaml")
    b = _write_manifest(tmp_path, _VALID_MANIFEST, filename="b.yaml")
    mock_client.deployments.apply_files = AsyncMock(
        side_effect=BatchNameConflictError("--name cannot be combined with multiple manifests")
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(a), "-f", str(b), "--name", "shared"])
    assert exc.value.code == 1

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "failed: --name cannot be combined with multiple manifests" in combined
    # Crucially: no per-outcome lines and no summary were emitted.
    assert "created" not in captured.out
    assert "updated" not in captured.out
    assert "0 created" not in captured.out


def test_deployments_apply_empty_directory(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """An empty directory → exit 1 with `failed: no manifests found in <path>`.

    The SDK's ``_expand_paths`` is what raises ``ApplyError("no manifests found
    in <dir>")`` before any transport work; we simulate that by having the
    mock raise the same exception with the same message. The CLI's job is to
    surface the message with the standard ``failed: <reason>`` prefix.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    mock_client.deployments.apply_files = AsyncMock(side_effect=ApplyError(f"no manifests found in {empty}"))

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(empty)])
    assert exc.value.code == 1

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "failed: no manifests found in" in combined
    assert str(empty) in combined


def test_deployments_apply_overrides_passed_to_sdk(
    mock_client: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI flags ONLY are forwarded as ``ApplyOverrides``; env vars stay in the SDK.

    Chunk 10 inverted the chunk-9 design: env-var resolution is now the SDK's
    job (see ``resolve_overrides`` in ``deployment_manifest.py``), so the CLI
    must not also peek at ``STYRMIN_*`` here — otherwise the env value would
    be applied twice and a flag-vs-env precedence bug would be invisible.
    """
    monkeypatch.delenv("STYRMIN_NAME", raising=False)
    monkeypatch.setenv("STYRMIN_ENVIRONMENT", "from-env")
    monkeypatch.setenv("STYRMIN_VERSION", "from-env-version")
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(return_value=[_outcome("my-app", "created")])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--version", "9.9.9", "--cluster", "c1"])
    assert exc.value.code == 0

    _args, kwargs = mock_client.deployments.apply_files.call_args
    overrides = kwargs["overrides"]
    # Only flag values are present; env-var values are deliberately NOT
    # mirrored here. The SDK's ``resolve_overrides`` is what reads env vars.
    assert overrides.name is None
    assert overrides.version == "9.9.9"
    assert overrides.environment is None
    assert overrides.cluster == "c1"


def test_deployments_apply_env_vars_not_read_at_cli(
    mock_client: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``STYRMIN_*`` env vars must NOT leak into the ``ApplyOverrides`` built by the CLI.

    This guards against the "double application" bug — if the CLI layered
    env vars onto ``overrides`` and the SDK *also* read env vars, then a
    later precedence change in either layer would silently desync.
    """
    monkeypatch.setenv("STYRMIN_NAME", "from-env")
    monkeypatch.setenv("STYRMIN_VERSION", "from-env")
    monkeypatch.setenv("STYRMIN_ENVIRONMENT", "from-env")
    monkeypatch.setenv("STYRMIN_CLUSTER", "from-env")
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(return_value=[_outcome("my-app", "created")])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0

    _args, kwargs = mock_client.deployments.apply_files.call_args
    overrides = kwargs["overrides"]
    assert overrides.name is None
    assert overrides.version is None
    assert overrides.environment is None
    assert overrides.cluster is None


def test_deployments_apply_env_only_resolution_via_sdk(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a manifest missing a field + ``STYRMIN_*`` set resolves cleanly.

    We use the *real* ``apply_files`` (no mock on the resource method)
    against a stubbed ``apply()`` so ``resolve_overrides`` actually runs
    against ``os.environ`` and we can observe its env-var precedence.
    """
    # Manifest without ``spec.version``; env var supplies it.
    body = (
        "apiVersion: styrmin/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: my-app\n"
        "spec:\n"
        "  driver: acme/web\n"
        "  environment: prod\n"
    )
    manifest = _write_manifest(tmp_path, body)
    monkeypatch.setenv("STYRMIN_VERSION", "1.5.0")

    captured_versions: list[str] = []

    async def fake_apply(resolved):  # type: ignore[no-untyped-def]  # noqa: RUF029 — async sig mirrors the real method
        captured_versions.append(resolved.version)
        return _outcome(resolved.name, "created")

    # Replace ``.apply`` but keep ``.apply_files`` (and the helpers it calls
    # into) as the real coroutines so ``resolve_overrides`` runs end-to-end.
    from styrmin_sdk.resources.deployments import DeploymentResource

    mock_client.deployments.apply_files = DeploymentResource.apply_files.__get__(mock_client.deployments)
    mock_client.deployments._dispatch_one = DeploymentResource._dispatch_one.__get__(mock_client.deployments)
    mock_client.deployments.apply = fake_apply

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0
    assert captured_versions == ["1.5.0"]
    assert "created my-app" in capsys.readouterr().out


def test_deployments_apply_cli_flag_overrides_env_var(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both ``--version`` and ``STYRMIN_VERSION`` are set, the flag wins."""
    body = (
        "apiVersion: styrmin/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: my-app\n"
        "spec:\n"
        "  driver: acme/web\n"
        "  environment: prod\n"
    )
    manifest = _write_manifest(tmp_path, body)
    monkeypatch.setenv("STYRMIN_VERSION", "1.5.0")

    captured_versions: list[str] = []

    async def fake_apply(resolved):  # type: ignore[no-untyped-def]  # noqa: RUF029 — async sig mirrors the real method
        captured_versions.append(resolved.version)
        return _outcome(resolved.name, "updated")

    from styrmin_sdk.resources.deployments import DeploymentResource

    mock_client.deployments.apply_files = DeploymentResource.apply_files.__get__(mock_client.deployments)
    mock_client.deployments._dispatch_one = DeploymentResource._dispatch_one.__get__(mock_client.deployments)
    mock_client.deployments.apply = fake_apply

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--version", "9.9.9"])
    assert exc.value.code == 0
    assert captured_versions == ["9.9.9"]
    assert "updated my-app" in capsys.readouterr().out


def test_deployments_apply_missing_required_field_message(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest missing a required field with no override → ``failed`` line names all three sources."""
    # Manifest is missing both ``spec.version`` and ``spec.environment``.
    # We clear the env vars so neither source can fill them in, leaving the
    # CLI flag as the only remaining option (which we also don't pass).
    body = "apiVersion: styrmin/v1\nkind: Deployment\nmetadata:\n  name: my-app\nspec:\n  driver: acme/web\n"
    manifest = _write_manifest(tmp_path, body)
    for var in ("STYRMIN_NAME", "STYRMIN_VERSION", "STYRMIN_ENVIRONMENT", "STYRMIN_CLUSTER"):
        monkeypatch.delenv(var, raising=False)

    from styrmin_sdk.resources.deployments import DeploymentResource

    mock_client.deployments.apply_files = DeploymentResource.apply_files.__get__(mock_client.deployments)
    mock_client.deployments.apply = AsyncMock()

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    # The line-level error from the SDK names the field and all three
    # sources so the user can pick whichever one fits their workflow.
    assert "version is required" in output
    assert "spec.version" in output
    assert "STYRMIN_VERSION" in output
    assert "--version" in output
    # ``apply()`` was never reached — the failure is pre-dispatch.
    mock_client.deployments.apply.assert_not_called()


def test_deployments_apply_styrmin_error_propagation(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Unexpected StyrminError from apply_files → exit 1 with `failed: <message>`."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(side_effect=StyrminError("transport down"))

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 1

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "failed: transport down" in combined


# --------------------------------------------------------------------------
# `--wait` two-line streaming output (chunk 11 / T045 / spec 009 §US4).
# --------------------------------------------------------------------------


def _wait_apply_files_stub(
    events_to_emit: list[tuple[Literal["submitted", "terminal"], ApplyOutcome]],
) -> AsyncMock:
    """Build an ``apply_files`` mock that drives ``on_event`` with a script.

    Each ``(event_type, outcome)`` tuple becomes one ``ApplyEvent`` callback
    invocation. The returned outcomes list is whatever the *terminal* events
    in the script carry — matching the SDK's contract that ``apply_files``
    returns post-wait outcomes in dispatch order.
    """
    from collections.abc import Callable
    from typing import cast

    from styrmin_sdk.models.deployment_manifest import ApplyEvent

    async def _apply_files(*_args: object, **kwargs: object) -> list[ApplyOutcome]:  # noqa: RUF029 — mirrors apply_files signature
        on_event = cast("Callable[[ApplyEvent], None] | None", kwargs.get("on_event"))
        outcomes: list[ApplyOutcome] = []
        for event_type, outcome in events_to_emit:
            if on_event is not None:
                on_event(ApplyEvent(type=event_type, name=outcome.name, outcome=outcome))
            if event_type == "terminal":
                outcomes.append(outcome)
            elif event_type == "submitted" and outcome.action == "failed":
                # Submission-failure outcomes never get a terminal event but
                # still appear in the returned outcomes list (per the SDK's
                # ``apply_files`` contract).
                outcomes.append(outcome)
        return outcomes

    return AsyncMock(side_effect=_apply_files)


def test_deployments_apply_wait_terminal_running_streams_two_lines(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--wait`` + terminal RUNNING → ``submitted X`` then ``running X`` → exit 0."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = _wait_apply_files_stub(
        [
            ("submitted", _outcome("my-app", "updated")),
            ("terminal", _outcome("my-app", "updated")),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait"])
    assert exc.value.code == 0

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line]
    assert lines[0] == "submitted my-app"
    assert lines[1] == "running my-app"
    # Summary uses post-wait counts.
    assert lines[-1] == "0 created, 1 updated, 0 unchanged, 0 failed"
    # Sanity: no plain ``updated my-app`` (single-line) bleed-through from
    # the chunk-9 path; ``--wait`` should fully replace per-outcome dump.
    assert "updated my-app" not in output


def test_deployments_apply_wait_terminal_failure_streams_failure_and_exits_one(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--wait`` + terminal failure → ``submitted X`` then ``failed X: ...`` → exit 1."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = _wait_apply_files_stub(
        [
            ("submitted", _outcome("my-app", "updated")),
            (
                "terminal",
                _outcome("my-app", "failed", reason="deployment reconciliation failed (status: failed)"),
            ),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait"])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line]
    assert lines[0] == "submitted my-app"
    assert lines[1] == "failed my-app: deployment reconciliation failed (status: failed)"
    assert lines[-1] == "0 created, 0 updated, 0 unchanged, 1 failed"


def test_deployments_apply_wait_failed_line_names_the_failed_step(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--wait`` + a failed step → the ``failed`` line keeps its shape and carries the SDK's step reason (FR-012)."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    reason = (
        'step "Install or upgrade the HelmRelease" failed: UpgradeFailed: Helm upgrade failed. '
        "Pods not ready: my-app-6d9 (app: ImagePullBackOff)"
    )
    mock_client.deployments.apply_files = _wait_apply_files_stub(
        [
            ("submitted", _outcome("my-app", "updated")),
            ("terminal", _outcome("my-app", "failed", reason=reason)),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait"])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line]
    assert lines[0] == "submitted my-app"
    assert lines[1] == f"failed my-app: {reason}"
    assert lines[-1] == "0 created, 0 updated, 0 unchanged, 1 failed"


def test_deployments_apply_wait_rejected_update_names_the_error_code(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--wait`` + an update the server rejects → the ``submitted`` event already
    carries the failure, its line ends with the server's code, and no terminal fires."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    reason = "Environment variables target component 'server', which declares no component container"
    rejected = ApplyOutcome(
        name="my-app",
        action="failed",
        deployment_id=UUID(DEPLOYMENT_UUID),
        failure_reason=reason,
        error_code="COMPONENT_CONTAINER_NOT_DECLARED",
    )
    mock_client.deployments.apply_files = _wait_apply_files_stub([("submitted", rejected)])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait"])
    assert exc.value.code == 1

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert lines == [
        f"failed my-app: {reason} [COMPONENT_CONTAINER_NOT_DECLARED]",
        "0 created, 0 updated, 0 unchanged, 1 failed",
    ]


def test_deployments_apply_wait_timeout_emits_failed_wait_timeout(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--wait`` + timeout → terminal event with ``failure_reason='wait timeout'``
    surfaces as ``failed <name>: wait timeout`` and exit 1."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = _wait_apply_files_stub(
        [
            ("submitted", _outcome("my-app", "updated")),
            ("terminal", _outcome("my-app", "failed", reason="wait timeout")),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait"])
    assert exc.value.code == 1

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line]
    assert lines[0] == "submitted my-app"
    assert lines[1] == "failed my-app: wait timeout"
    assert lines[-1] == "0 created, 0 updated, 0 unchanged, 1 failed"


def test_deployments_apply_wait_passes_flag_through_to_sdk(
    mock_client: MagicMock,
    tmp_path: Path,
) -> None:
    """``--wait`` propagates ``wait=True`` and an ``on_event`` callback to the SDK."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = _wait_apply_files_stub(
        [
            ("submitted", _outcome("my-app", "updated")),
            ("terminal", _outcome("my-app", "updated")),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait"])
    assert exc.value.code == 0

    _args, kwargs = mock_client.deployments.apply_files.call_args
    assert kwargs["wait"] is True
    assert kwargs["max_wait"] == 600
    assert kwargs["on_event"] is not None


def test_deployments_apply_max_wait_passes_through_to_sdk(
    mock_client: MagicMock,
    tmp_path: Path,
) -> None:
    """``--max-wait`` sets the SDK's wait limit."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = _wait_apply_files_stub(
        [
            ("submitted", _outcome("my-app", "updated")),
            ("terminal", _outcome("my-app", "updated")),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait", "--max-wait", "900"])
    assert exc.value.code == 0

    _args, kwargs = mock_client.deployments.apply_files.call_args
    assert kwargs["max_wait"] == 900


def test_deployments_apply_rejects_non_positive_max_wait(
    mock_client: MagicMock,
    tmp_path: Path,
) -> None:
    """A ``--max-wait`` of 0 fails before the SDK is called."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait", "--max-wait", "0"])
    assert exc.value.code != 0
    mock_client.deployments.apply_files.assert_not_awaited()


def test_deployments_apply_no_wait_does_not_install_callback(
    mock_client: MagicMock,
    tmp_path: Path,
) -> None:
    """Without ``--wait``, the SDK is called with ``wait=False`` and no callback,
    preserving the chunk-9 fire-and-forget output path."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(return_value=[_outcome("my-app", "created")])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0

    _args, kwargs = mock_client.deployments.apply_files.call_args
    assert kwargs["wait"] is False
    assert kwargs["on_event"] is None


# --------------------------------------------------------------------------
# Pinned image override warning (018, FR-008): stderr only, exit code unchanged.
# --------------------------------------------------------------------------

_PINNED_WARNING = (
    "warning: my-app: pinned image override on server will not follow version 1.1.0 (no {{ app.version }} token)"
)


def _pinned_outcome(name: str, components: list[str]) -> ApplyOutcome:
    return _outcome(name, "updated").model_copy(
        update={"pinned_image_components": components, "target_version": "1.1.0"}
    )


def test_deployments_apply_prints_pinned_image_warning_to_stderr(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(
        return_value=[_outcome("other", "created"), _pinned_outcome("my-app", ["server"])]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0

    captured = capsys.readouterr()
    assert captured.err.splitlines() == [_PINNED_WARNING]
    assert "warning:" not in captured.out
    assert captured.out.splitlines() == [
        "created other",
        "updated my-app",
        "1 created, 1 updated, 0 unchanged, 0 failed",
    ]


def test_deployments_apply_pinned_warning_names_every_component(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(return_value=[_pinned_outcome("my-app", ["server", "worker"])])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0

    assert capsys.readouterr().err.splitlines() == [
        "warning: my-app: pinned image overrides on server, worker will not follow version 1.1.0 "
        "(no {{ app.version }} token)"
    ]


def test_deployments_apply_pinned_warning_keeps_failure_exit_code(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    mock_client.deployments.apply_files = AsyncMock(
        return_value=[_pinned_outcome("my-app", ["server"]), _outcome("broken", "failed", reason="boom")]
    )

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 1

    assert capsys.readouterr().err.splitlines() == [_PINNED_WARNING]


def test_deployments_apply_warns_about_overrides_the_driver_version_cannot_apply(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    outcome = _outcome("my-app", "updated").model_copy(update={"inapplicable_components": ["worker"]})
    mock_client.deployments.apply_files = AsyncMock(return_value=[outcome])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest)])
    assert exc.value.code == 0

    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "warning: my-app: env vars and image overrides on worker are stored but not applied "
        "(no component container in the driver version)"
    ]
    assert captured.out.splitlines() == ["updated my-app", "0 created, 1 updated, 0 unchanged, 0 failed"]


def test_deployments_apply_wait_prints_pinned_warning_once_on_submit(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The warning lands with the ``submitted`` line, before the wait, and is not repeated."""
    manifest = _write_manifest(tmp_path, _VALID_MANIFEST)
    pinned = _pinned_outcome("my-app", ["server"])
    mock_client.deployments.apply_files = _wait_apply_files_stub([("submitted", pinned), ("terminal", pinned)])

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "apply", "-f", str(manifest), "--wait"])
    assert exc.value.code == 0

    captured = capsys.readouterr()
    assert captured.err.splitlines() == [_PINNED_WARNING]
    assert captured.out.splitlines() == [
        "submitted my-app",
        "running my-app",
        "0 created, 1 updated, 0 unchanged, 0 failed",
    ]
