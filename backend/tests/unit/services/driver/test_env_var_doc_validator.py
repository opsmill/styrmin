"""Unit tests for the driver-side env var documentation models (008 / US4).

Covers FR-013/FR-014: name regex, level/components consistency, name
uniqueness within the list, components-must-exist cross-field validation,
and registration-aborts-on-bad-doc behaviour.

Mirrors the shape of ``test_driver_parameters.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from styrmin_backend.services.driver.models.resources.driver import (
    ArbitrarySectionModel,
    Components,
    DriverSpec,
    Helm,
    HelmSettings,
    Identifier,
    Info,
    LabelIdentifier,
    Specification,
)
from styrmin_backend.services.driver.models.resources.env_vars import (
    DriverEnvVarDoc,
    DriverEnvVarLevel,
    validate_env_var_doc_names_unique,
)
from styrmin_backend.services.driver.validators import validate_driver_env_var_docs
from styrmin_backend.services.env_vars.exceptions import (
    DriverEnvVarDocComponentMismatchError,
    InvalidEnvVarNameError,
)


def _make_specification(
    *,
    components: dict[str, ArbitrarySectionModel] | None = None,
    env_vars: list[DriverEnvVarDoc] | None = None,
) -> Specification:
    """Build a minimal valid :class:`Specification` for cross-field tests.

    Components default to a small ``{server, database}`` set so the tests
    can check both happy and unhappy cross-references.
    """
    if components is None:
        components = {
            "server": ArbitrarySectionModel(
                identifier=Identifier(label=LabelIdentifier(root={"app": "server"})),
            ),
            "database": ArbitrarySectionModel(
                identifier=Identifier(label=LabelIdentifier(root={"app": "db"})),
            ),
        }
    return Specification(
        version="1",
        supported_versions=">=0.1,<1.0",
        info=Info(),
        helm=Helm(main=HelmSettings(location="oci://example", version="1.0.0")),
        components=Components(root=components),
        env_vars=env_vars,
    )


# ---------------------------------------------------------------------------
# DriverEnvVarDoc field-level validation (name regex, level/components shape)
# ---------------------------------------------------------------------------


class TestDriverEnvVarDocNameRegex:
    """Per-entry name validation (FR-006 reused at driver-load time)."""

    @pytest.mark.parametrize(
        "name",
        ["LOG_LEVEL", "_PRIVATE", "X1", "OTEL_EXPORTER_OTLP_ENDPOINT"],
    )
    def test_valid_names_accepted(self, name: str) -> None:
        doc = DriverEnvVarDoc(
            name=name, description="ok", level=DriverEnvVarLevel.DEPLOYMENT
        )
        assert doc.name == name

    @pytest.mark.parametrize(
        "name",
        ["1BAD", "", "WITH-HYPHEN", "WITH SPACE", "lower.case", "$NOPE"],
    )
    def test_invalid_names_rejected(self, name: str) -> None:
        # ``InvalidEnvVarNameError`` is a ``ServiceError`` (not ``ValueError``),
        # so Pydantic propagates it directly rather than wrapping it in a
        # ``ValidationError``. That's intentional — the loader path keeps the
        # typed error so callers can match on ``error_code`` without
        # unwrapping a Pydantic envelope.
        with pytest.raises(InvalidEnvVarNameError) as exc_info:
            DriverEnvVarDoc(
                name=name, description="x", level=DriverEnvVarLevel.DEPLOYMENT
            )
        assert exc_info.value.name == name


class TestDriverEnvVarDocLevelComponentsShape:
    """``level=component`` requires components; ``level=deployment`` forbids them."""

    def test_deployment_level_with_no_components_accepted(self) -> None:
        doc = DriverEnvVarDoc(
            name="LOG_LEVEL", description="x", level=DriverEnvVarLevel.DEPLOYMENT
        )
        assert doc.components == []

    def test_component_level_with_components_accepted(self) -> None:
        doc = DriverEnvVarDoc(
            name="DB_POOL_SIZE",
            description="x",
            level=DriverEnvVarLevel.COMPONENT,
            components=["database"],
        )
        assert doc.components == ["database"]

    def test_component_level_without_components_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="level='component' requires a non-empty"
        ):
            DriverEnvVarDoc(
                name="X", description="x", level=DriverEnvVarLevel.COMPONENT
            )

    def test_deployment_level_with_components_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="level='deployment' MUST NOT name components"
        ):
            DriverEnvVarDoc(
                name="X",
                description="x",
                level=DriverEnvVarLevel.DEPLOYMENT,
                components=["server"],
            )


# ---------------------------------------------------------------------------
# Name uniqueness within the list (FR-013)
# ---------------------------------------------------------------------------


class TestEnvVarDocNameUniqueness:
    def test_unique_names_accepted(self) -> None:
        docs = [
            DriverEnvVarDoc(
                name="LOG_LEVEL", description="x", level=DriverEnvVarLevel.DEPLOYMENT
            ),
            DriverEnvVarDoc(
                name="OTEL_ENDPOINT",
                description="x",
                level=DriverEnvVarLevel.DEPLOYMENT,
            ),
        ]
        assert validate_env_var_doc_names_unique(docs) is docs

    def test_duplicate_names_rejected(self) -> None:
        docs = [
            DriverEnvVarDoc(
                name="LOG_LEVEL", description="x", level=DriverEnvVarLevel.DEPLOYMENT
            ),
            DriverEnvVarDoc(
                name="LOG_LEVEL", description="y", level=DriverEnvVarLevel.DEPLOYMENT
            ),
        ]
        with pytest.raises(ValueError, match="Duplicate driver env var doc names"):
            validate_env_var_doc_names_unique(docs)

    def test_specification_field_validator_rejects_duplicates(self) -> None:
        """The ``Specification`` field validator wires the uniqueness check."""
        with pytest.raises(ValidationError, match="Duplicate driver env var doc names"):
            _make_specification(
                env_vars=[
                    DriverEnvVarDoc(
                        name="LOG_LEVEL",
                        description="x",
                        level=DriverEnvVarLevel.DEPLOYMENT,
                    ),
                    DriverEnvVarDoc(
                        name="LOG_LEVEL",
                        description="y",
                        level=DriverEnvVarLevel.DEPLOYMENT,
                    ),
                ]
            )


# ---------------------------------------------------------------------------
# Cross-field: components must exist in Specification.components
# ---------------------------------------------------------------------------


class TestComponentReferencesValidator:
    def test_no_env_vars_is_no_op(self) -> None:
        spec = _make_specification(env_vars=None)
        validate_driver_env_var_docs(spec)  # no exception

    def test_deployment_level_skips_component_check(self) -> None:
        spec = _make_specification(
            env_vars=[
                DriverEnvVarDoc(
                    name="LOG_LEVEL",
                    description="x",
                    level=DriverEnvVarLevel.DEPLOYMENT,
                )
            ]
        )
        validate_driver_env_var_docs(spec)

    def test_component_reference_resolves_against_declared_components(self) -> None:
        spec = _make_specification(
            env_vars=[
                DriverEnvVarDoc(
                    name="DB_POOL_SIZE",
                    description="x",
                    level=DriverEnvVarLevel.COMPONENT,
                    components=["database"],
                )
            ]
        )
        validate_driver_env_var_docs(spec)

    def test_unknown_component_reference_rejected(self) -> None:
        spec = _make_specification(
            env_vars=[
                DriverEnvVarDoc(
                    name="DB_POOL_SIZE",
                    description="x",
                    level=DriverEnvVarLevel.COMPONENT,
                    components=["does-not-exist"],
                )
            ]
        )
        with pytest.raises(DriverEnvVarDocComponentMismatchError) as exc_info:
            validate_driver_env_var_docs(spec)
        err = exc_info.value
        assert err.name == "DB_POOL_SIZE"
        assert err.component_name == "does-not-exist"
        assert err.known_components == ["database", "server"]
        assert err.error_code == "DRIVER_ENV_VAR_DOC_COMPONENT_MISMATCH"

    def test_partial_unknown_component_reference_rejected(self) -> None:
        """One good + one bad reference still fails on the bad one."""
        spec = _make_specification(
            env_vars=[
                DriverEnvVarDoc(
                    name="DB_POOL_SIZE",
                    description="x",
                    level=DriverEnvVarLevel.COMPONENT,
                    components=["database", "ghost"],
                )
            ]
        )
        with pytest.raises(DriverEnvVarDocComponentMismatchError) as exc_info:
            validate_driver_env_var_docs(spec)
        assert exc_info.value.component_name == "ghost"


# ---------------------------------------------------------------------------
# Registration-aborts-on-bad-doc — full DriverSpec parse + cross-field check.
# ---------------------------------------------------------------------------


class TestRegistrationAbortsOnBadDoc:
    """Drives a YAML-shaped payload through ``DriverSpec`` + cross-field
    validation as the loader does in ``services/driver/loaders.py``.
    """

    @staticmethod
    def _payload(env_vars: list[dict] | None) -> dict:
        return {
            "apiVersion": "styrmin.io/v1",
            "kind": "ApplicationDriver",
            "metadata": {"name": "demo"},
            "spec": {
                "version": "1",
                "supported_versions": ">=0.1,<1.0",
                "info": {},
                "helm": {"main": {"location": "oci://example", "version": "1.0.0"}},
                "components": {
                    "server": {
                        "identifier": {"label": {"app.kubernetes.io/name": "demo"}},
                    },
                },
                "env_vars": env_vars,
            },
        }

    def test_well_formed_doc_parses(self) -> None:
        ds = DriverSpec.model_validate(
            self._payload(
                [
                    {
                        "name": "LOG_LEVEL",
                        "description": "log level",
                        "level": "deployment",
                    },
                    {
                        "name": "PORT",
                        "description": "port",
                        "level": "component",
                        "components": ["server"],
                    },
                ]
            )
        )
        validate_driver_env_var_docs(ds.spec)
        assert ds.spec.env_vars is not None
        assert len(ds.spec.env_vars) == 2

    def test_invalid_name_aborts_pydantic_parse(self) -> None:
        # ``InvalidEnvVarNameError`` propagates directly (it's a
        # ``ServiceError``, not a ``ValueError``).
        with pytest.raises(InvalidEnvVarNameError):
            DriverSpec.model_validate(
                self._payload(
                    [
                        {
                            "name": "1BAD",
                            "description": "x",
                            "level": "deployment",
                        }
                    ]
                )
            )

    def test_unknown_component_aborts_at_cross_field_step(self) -> None:
        ds = DriverSpec.model_validate(
            self._payload(
                [
                    {
                        "name": "LOG_LEVEL",
                        "description": "x",
                        "level": "component",
                        "components": ["does-not-exist"],
                    }
                ]
            )
        )
        with pytest.raises(DriverEnvVarDocComponentMismatchError):
            validate_driver_env_var_docs(ds.spec)
