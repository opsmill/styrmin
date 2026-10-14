"""Deployment manifest models.

Pydantic models backing the YAML deployment manifest user contract
(`apiVersion: styrmin/v1`, `kind: Deployment`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from styrmin_sdk.exceptions import MissingRequiredFieldError


class _Metadata(BaseModel):
    """Metadata block of a deployment manifest. `name` is optional in the YAML
    (it can be supplied via override at resolve-time)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None


class _Spec(BaseModel):
    """Spec block of a deployment manifest.

    Only `driver` is required in the YAML; the other identity fields
    (`version`, `environment`) are optional in the manifest itself and may be
    supplied via overrides at resolve-time. `config` and `parameters` default
    to empty dicts.
    """

    model_config = ConfigDict(extra="forbid")

    driver: str = Field(..., min_length=1)
    version: str | None = None
    environment: str | None = None
    cluster: str | None = None
    config: dict[str, JsonValue] = Field(default_factory=dict)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class DeploymentManifest(BaseModel):
    """Parsed user-authored YAML manifest.

    The YAML-derived fields are validated under `extra="forbid"`. The source
    file path is *not* part of the YAML contract: the loader sets it on the
    instance after `model_validate` via the dedicated `with_source_path()`
    helper, which is why it lives outside the model rather than as a field
    here. (Adding it as a model field would either break `extra="forbid"` for
    the YAML or force users to set a leading-underscore key in their YAML.)
    """

    model_config = ConfigDict(extra="forbid")

    apiVersion: Literal["styrmin/v1"]  # noqa: N815 — public YAML key
    kind: Literal["Deployment"]
    metadata: _Metadata = Field(default_factory=_Metadata)
    spec: _Spec


class ResolvedManifest(BaseModel):
    """Manifest after override resolution.

    All required identity fields are guaranteed present. `source_path` is
    carried for path-prefixed error messages downstream.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    driver: str
    version: str
    environment: str
    cluster: str | None = None
    config: dict[str, JsonValue] = Field(default_factory=dict)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    source_path: Path


class ApplyOverrides(BaseModel):
    """Overrides supplied via CLI flags or environment variables.

    Each field is optional; unset overrides leave the manifest value in place.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    version: str | None = None
    environment: str | None = None
    cluster: str | None = None


class ApplyOutcome(BaseModel):
    """Result of applying a single manifest."""

    model_config = ConfigDict(extra="forbid")

    name: str
    action: Literal["created", "updated", "unchanged", "failed"]
    deployment_id: UUID | None = None
    task_id: UUID | None = None
    failure_reason: str | None = None
    # The server's error code (`extensions.code`) when the server rejected the manifest.
    error_code: str | None = None
    # Set only when `apply` changes an existing deployment's application version.
    target_version: str | None = None
    # Components whose effective image override has no `{{ app.version }}` token (FR-008).
    pinned_image_components: list[str] = Field(default_factory=list)
    # Components whose env vars, image, `command` or `args` the manifest sets but the bound
    # driver version cannot apply: they are stored, not applied.
    inapplicable_components: list[str] = Field(default_factory=list)


class ApplyEvent(BaseModel):
    """Streaming event emitted by ``apply_files`` during ``--wait`` polling.

    Two event types are emitted, in order, for each manifest that reaches the
    dispatch phase:

    * ``submitted`` — the SDK has finished dispatching the create/update
      mutation. ``outcome`` carries the post-submit (pre-wait) state, so the
      CLI can decide between ``submitted <name>`` (success path) and
      ``failed <name>: <reason>`` (validation/dispatch failure) without
      re-deriving anything.
    * ``terminal`` — the deployment has settled (``RUNNING``, a documented
      failure status, or a wait timeout). ``outcome`` carries the post-wait
      state, including ``action="failed"`` + ``failure_reason`` when the
      reconciliation did not succeed.

    Events are only emitted when ``apply_files`` is called with
    ``wait=True``. Without ``wait=True`` the existing return-list path is the
    only signal — see ``contracts/sdk-apply.md`` for the rationale.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["submitted", "terminal"]
    name: str
    outcome: ApplyOutcome


# Mapping from override field name to the corresponding ``STYRMIN_*`` env var.
# ``cluster`` is included for completeness even though it's never required.
_ENV_VAR_BY_FIELD: dict[str, str] = {
    "name": "STYRMIN_NAME",
    "version": "STYRMIN_VERSION",
    "environment": "STYRMIN_ENVIRONMENT",
    "cluster": "STYRMIN_CLUSTER",
}


def _pick(
    field: str,
    *,
    override_value: str | None,
    env: Mapping[str, str],
    manifest_value: str | None,
) -> str | None:
    """Apply CLI > env > manifest precedence for one field.

    A value is "set" when it is a non-empty string; empty strings from any
    source are treated as absent so that ``STYRMIN_VERSION=""`` does not
    blank out a manifest's version field.
    """
    if override_value:
        return override_value
    env_value = env.get(_ENV_VAR_BY_FIELD[field])
    if env_value:
        return env_value
    if manifest_value:
        return manifest_value
    return None


def resolve_overrides(
    manifest: DeploymentManifest,
    overrides: ApplyOverrides,
    env: Mapping[str, str],
    *,
    source_path: Path,
) -> ResolvedManifest:
    """Resolve a ``DeploymentManifest`` against overrides and env vars.

    Precedence per field is **CLI flag > env var > manifest field**: if an
    ``ApplyOverrides`` field is set it wins; otherwise the ``STYRMIN_<FIELD>``
    env var is consulted; otherwise the manifest's own value is used. This is
    the standard precedence for CI-promotable tooling: local dev sets the
    YAML, CI sets the env, and an operator's flag always wins for ad-hoc work.

    Required-after-resolution fields are ``name``, ``driver``, ``version``,
    and ``environment``. ``cluster`` is always optional (it disambiguates
    same-named environments across clusters). ``driver`` is special: it has
    NO override surface — only the manifest can set it — so its error
    message names only the manifest source.

    On a missing required field this raises :class:`MissingRequiredFieldError`
    with a message that names the field and all three sources (manifest YAML
    path, env var name, and CLI flag) so the user can pick whichever fits
    their workflow.

    Args:
        manifest: The parsed YAML manifest.
        overrides: CLI flag values (any field may be ``None``).
        env: A mapping (typically ``os.environ``) consulted for
            ``STYRMIN_*`` keys. Pass an empty dict to ignore env vars.
        source_path: Path to the source YAML file, attached to the
            returned ``ResolvedManifest`` for downstream error messages.

    Returns:
        A ``ResolvedManifest`` with all required identity fields populated.
    """
    name = _pick("name", override_value=overrides.name, env=env, manifest_value=manifest.metadata.name)
    version = _pick("version", override_value=overrides.version, env=env, manifest_value=manifest.spec.version)
    environment = _pick(
        "environment",
        override_value=overrides.environment,
        env=env,
        manifest_value=manifest.spec.environment,
    )
    cluster = _pick("cluster", override_value=overrides.cluster, env=env, manifest_value=manifest.spec.cluster)

    # Driver has no override surface — manifest is the only source. Defence
    # in depth: _Spec.driver enforces min_length=1, but a resolver-layer guard
    # is kept so callers that bypass model validation still get a typed error.
    driver = manifest.spec.driver
    if not driver:
        raise MissingRequiredFieldError(
            f"manifest {source_path}: driver is required and cannot be overridden (set spec.driver in the YAML)",
        )

    if not name:
        raise MissingRequiredFieldError(
            f"manifest {source_path}: name is required "
            "(set in metadata.name, env var STYRMIN_NAME, or CLI flag --name)",
        )
    if not version:
        raise MissingRequiredFieldError(
            f"manifest {source_path}: version is required "
            "(set in spec.version, env var STYRMIN_VERSION, or CLI flag --version)",
        )
    if not environment:
        raise MissingRequiredFieldError(
            f"manifest {source_path}: environment is required "
            "(set in spec.environment, env var STYRMIN_ENVIRONMENT, or CLI flag --environment)",
        )

    return ResolvedManifest(
        name=name,
        driver=driver,
        version=version,
        environment=environment,
        cluster=cluster,
        config=manifest.spec.config,
        parameters=manifest.spec.parameters,
        source_path=source_path,
    )
