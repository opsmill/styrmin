"""Unit tests for ``resolve_overrides`` (chunk 10 / T037).

Covers the CLI > env > manifest precedence contract from
``specs/009-deployments-apply/contracts/sdk-apply.md`` and ``research.md`` D4.
The fixture matrix is intentionally exhaustive on the ``name`` field — once
precedence is proven there, the same ``_pick`` runs for ``version``,
``environment`` and ``cluster``, so per-field combinatorial tests would be
redundant.

Required-after-resolution coverage walks each of ``name``, ``version``,
``environment``, and ``driver`` once; ``cluster`` gets a dedicated never-
required test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from styrmin_sdk.exceptions import MissingRequiredFieldError
from styrmin_sdk.models.deployment_manifest import (
    ApplyOverrides,
    DeploymentManifest,
    resolve_overrides,
)

SOURCE = Path("/tmp/manifest.yaml")  # noqa: S108 — purely a label, not a real file.


def _manifest(
    *,
    name: str | None = "manifest-name",
    driver: str = "acme/web",
    version: str | None = "1.0.0",
    environment: str | None = "prod",
    cluster: str | None = None,
) -> DeploymentManifest:
    """Build a parsed manifest with override-eligible fields toggleable.

    Defaults populate every field so each test only has to declare what it
    explicitly wants absent. ``driver`` is always set unless a test overrides
    it (driver has no override path, so that's always the failure mode).
    """
    return DeploymentManifest.model_validate(
        {
            "apiVersion": "styrmin/v1",
            "kind": "Deployment",
            "metadata": {"name": name} if name is not None else {},
            "spec": {
                "driver": driver,
                **({"version": version} if version is not None else {}),
                **({"environment": environment} if environment is not None else {}),
                **({"cluster": cluster} if cluster is not None else {}),
            },
        }
    )


# --- Precedence: 2x2x2 matrix on ``name`` (manifest set / env set / flag set) -----


@pytest.mark.parametrize(
    ("manifest_name", "env_name", "flag_name", "expected"),
    [
        # All three set → flag wins.
        ("from-manifest", "from-env", "from-flag", "from-flag"),
        # Manifest+env, no flag → env wins.
        ("from-manifest", "from-env", None, "from-env"),
        # Manifest+flag, no env → flag wins.
        ("from-manifest", None, "from-flag", "from-flag"),
        # Env+flag, no manifest → flag wins.
        (None, "from-env", "from-flag", "from-flag"),
        # Manifest only → manifest used.
        ("from-manifest", None, None, "from-manifest"),
        # Env only → env used.
        (None, "from-env", None, "from-env"),
        # Flag only → flag used.
        (None, None, "from-flag", "from-flag"),
    ],
)
def test_name_precedence_matrix(
    manifest_name: str | None,
    env_name: str | None,
    flag_name: str | None,
    expected: str,
) -> None:
    """The 7 set/unset combinations all resolve to the documented winner."""
    manifest = _manifest(name=manifest_name)
    overrides = ApplyOverrides(name=flag_name)
    env = {"STYRMIN_NAME": env_name} if env_name is not None else {}

    resolved = resolve_overrides(manifest, overrides, env, source_path=SOURCE)
    assert resolved.name == expected


def test_name_all_unset_raises_missing() -> None:
    """The 8th matrix combination — every source absent → ``MissingRequiredFieldError``."""
    manifest = _manifest(name=None)
    overrides = ApplyOverrides()
    with pytest.raises(MissingRequiredFieldError) as exc_info:
        resolve_overrides(manifest, overrides, {}, source_path=SOURCE)
    msg = str(exc_info.value)
    assert "name is required" in msg
    assert "metadata.name" in msg
    assert "STYRMIN_NAME" in msg
    assert "--name" in msg


# --- Precedence is consistent across the other override-eligible fields ----------


def test_version_flag_wins_over_env() -> None:
    manifest = _manifest(version="1.0.0")
    overrides = ApplyOverrides(version="9.9.9")
    env = {"STYRMIN_VERSION": "5.5.5"}
    assert resolve_overrides(manifest, overrides, env, source_path=SOURCE).version == "9.9.9"


def test_environment_env_var_wins_over_manifest() -> None:
    manifest = _manifest(environment="prod")
    env = {"STYRMIN_ENVIRONMENT": "staging"}
    assert resolve_overrides(manifest, ApplyOverrides(), env, source_path=SOURCE).environment == "staging"


def test_cluster_flag_wins_over_env_and_manifest() -> None:
    manifest = _manifest(cluster="m-cluster")
    overrides = ApplyOverrides(cluster="flag-cluster")
    env = {"STYRMIN_CLUSTER": "env-cluster"}
    assert resolve_overrides(manifest, overrides, env, source_path=SOURCE).cluster == "flag-cluster"


# --- Required-field error coverage -----------------------------------------------


def test_missing_version_lists_three_sources() -> None:
    manifest = _manifest(version=None)
    with pytest.raises(MissingRequiredFieldError) as exc_info:
        resolve_overrides(manifest, ApplyOverrides(), {}, source_path=SOURCE)
    msg = str(exc_info.value)
    assert "version is required" in msg
    assert "spec.version" in msg
    assert "STYRMIN_VERSION" in msg
    assert "--version" in msg


def test_missing_environment_lists_three_sources() -> None:
    manifest = _manifest(environment=None)
    with pytest.raises(MissingRequiredFieldError) as exc_info:
        resolve_overrides(manifest, ApplyOverrides(), {}, source_path=SOURCE)
    msg = str(exc_info.value)
    assert "environment is required" in msg
    assert "spec.environment" in msg
    assert "STYRMIN_ENVIRONMENT" in msg
    assert "--environment" in msg


def test_missing_driver_names_only_manifest_source() -> None:
    """Driver has no override surface — its message must NOT advertise env/flag.

    The model itself enforces ``driver`` non-empty so we use a model-bypass
    construction to drive the unset branch; this guards the safety net at
    the resolver layer too.
    """

    # Build a manifest with a driver that fails the resolver's own check
    # without going through model validation (which would reject it).
    from typing import ClassVar

    class _FakeSpec:
        driver = ""
        version = "1.0.0"
        environment = "prod"
        cluster: str | None = None
        config: ClassVar[dict] = {}  # type: ignore[type-arg]
        parameters: ClassVar[dict] = {}  # type: ignore[type-arg]

    class _FakeMeta:
        name = "my-app"

    class _FakeManifest:
        metadata = _FakeMeta()
        spec = _FakeSpec()

    with pytest.raises(MissingRequiredFieldError) as exc_info:
        resolve_overrides(_FakeManifest(), ApplyOverrides(), {}, source_path=SOURCE)  # type: ignore[arg-type]
    msg = str(exc_info.value)
    assert "driver is required" in msg
    assert "spec.driver" in msg
    # Driver has no override surface — these MUST be absent.
    assert "STYRMIN" not in msg
    assert "--" not in msg.split("driver is required", 1)[1].split("\n", 1)[0] or "--" not in msg


# --- ``cluster`` is never required -----------------------------------------------


def test_cluster_absent_from_all_sources_resolves_cleanly() -> None:
    """No cluster anywhere is fine — cluster is a disambiguator, not a key."""
    manifest = _manifest(cluster=None)
    resolved = resolve_overrides(manifest, ApplyOverrides(), {}, source_path=SOURCE)
    assert resolved.cluster is None


# --- Integration: source_path threading + config/parameters pass-through ---------


def test_source_path_and_payload_flow_through() -> None:
    manifest = _manifest()
    manifest = manifest.model_copy(
        update={
            "spec": manifest.spec.model_copy(
                update={"config": {"a": 1}, "parameters": {"b": 2}},
            ),
        },
    )
    resolved = resolve_overrides(manifest, ApplyOverrides(), {}, source_path=SOURCE)
    assert resolved.source_path == SOURCE
    assert resolved.config == {"a": 1}
    assert resolved.parameters == {"b": 2}


def test_manifest_only_name_with_flag_means_flag_wins() -> None:
    """Explicit US3 case: manifest sets ``metadata.name`` AND ``--name`` is passed."""
    manifest = _manifest(name="from-manifest")
    overrides = ApplyOverrides(name="from-flag")
    resolved = resolve_overrides(manifest, overrides, {}, source_path=SOURCE)
    assert resolved.name == "from-flag"


def test_empty_string_env_var_is_treated_as_absent() -> None:
    """``STYRMIN_VERSION=""`` must not blank-out a manifest's version field.

    Empty strings are a common shell footgun (``export STYRMIN_VERSION=`` in
    a sourced ``.env`` file), so the resolver treats them like the variable
    being unset.
    """
    manifest = _manifest(version="1.0.0")
    env = {"STYRMIN_VERSION": ""}
    assert resolve_overrides(manifest, ApplyOverrides(), env, source_path=SOURCE).version == "1.0.0"
