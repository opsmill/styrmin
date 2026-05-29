"""Unit tests for the driver-side container-override doc models (014 / US6).

Covers the load-time safety contract for ``spec.container_overrides``:

* per-entry component uniqueness (``validate_container_override_doc_components_unique``
  + the ``Specification`` field validator that wires it);
* cross-field "every referenced component must be declared"
  (``validate_driver_container_override_docs``), which aborts registration on a
  dangling reference;
* the full ``DriverSpec`` parse + cross-field path the loader runs.

Mirrors ``test_env_var_doc_validator.py``; the env-vars precedent is the
authority for the shape of these tests (research.md D5 / SC-004).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from styrmin_backend.services.container_overrides.exceptions import (
    DriverContainerOverrideDocComponentMismatchError,
)
from styrmin_backend.services.driver.models.resources.container_overrides import (
    DriverContainerOverrideDoc,
    validate_container_override_doc_components_unique,
)
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
from styrmin_backend.services.driver.validators import (
    validate_driver_container_override_docs,
)


def _make_specification(
    *,
    components: dict[str, ArbitrarySectionModel] | None = None,
    container_overrides: list[DriverContainerOverrideDoc] | None = None,
) -> Specification:
    """Build a minimal valid :class:`Specification` for cross-field tests.

    Components default to ``{server, database}`` so the tests can check both
    happy and unhappy cross-references.
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
        container_overrides=container_overrides,
    )


# ---------------------------------------------------------------------------
# Per-entry shape: doc-only fields, defaults
# ---------------------------------------------------------------------------


class TestDriverContainerOverrideDocShape:
    def test_minimal_entry_defaults(self) -> None:
        doc = DriverContainerOverrideDoc(component="server")
        assert doc.component == "server"
        assert doc.description == ""
        assert doc.container is None
        assert doc.command is False
        assert doc.args is False

    def test_full_entry(self) -> None:
        doc = DriverContainerOverrideDoc(
            component="server",
            description="override the entrypoint",
            container="app",
            command=True,
            args=True,
        )
        assert doc.command is True
        assert doc.args is True

    def test_extra_keys_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            DriverContainerOverrideDoc.model_validate(
                {"component": "server", "unexpected": "x"}
            )


# ---------------------------------------------------------------------------
# Component uniqueness within the list
# ---------------------------------------------------------------------------


class TestComponentUniqueness:
    def test_unique_components_accepted(self) -> None:
        docs = [
            DriverContainerOverrideDoc(component="server"),
            DriverContainerOverrideDoc(component="database"),
        ]
        assert validate_container_override_doc_components_unique(docs) is docs

    def test_duplicate_components_rejected(self) -> None:
        docs = [
            DriverContainerOverrideDoc(component="server", command=True),
            DriverContainerOverrideDoc(component="server", args=True),
        ]
        with pytest.raises(
            ValueError, match="Duplicate driver container_overrides components"
        ):
            validate_container_override_doc_components_unique(docs)

    def test_specification_field_validator_rejects_duplicates(self) -> None:
        """The ``Specification`` field validator wires the uniqueness check."""
        with pytest.raises(
            ValidationError, match="Duplicate driver container_overrides components"
        ):
            _make_specification(
                container_overrides=[
                    DriverContainerOverrideDoc(component="server", command=True),
                    DriverContainerOverrideDoc(component="server", args=True),
                ]
            )


# ---------------------------------------------------------------------------
# Cross-field: every referenced component must exist in Specification.components
# ---------------------------------------------------------------------------


class TestComponentReferencesValidator:
    def test_no_container_overrides_is_no_op(self) -> None:
        spec = _make_specification(container_overrides=None)
        validate_driver_container_override_docs(spec)  # no exception

    def test_declared_component_reference_resolves(self) -> None:
        spec = _make_specification(
            container_overrides=[
                DriverContainerOverrideDoc(component="database", command=True)
            ]
        )
        validate_driver_container_override_docs(spec)

    def test_unknown_component_reference_rejected(self) -> None:
        spec = _make_specification(
            container_overrides=[
                DriverContainerOverrideDoc(component="does-not-exist", command=True)
            ]
        )
        with pytest.raises(
            DriverContainerOverrideDocComponentMismatchError
        ) as exc_info:
            validate_driver_container_override_docs(spec)
        err = exc_info.value
        assert err.component_name == "does-not-exist"
        assert err.known_components == ["database", "server"]
        assert err.error_code == "DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH"
        assert err.error_metadata["known_components"] == ["database", "server"]

    def test_partial_unknown_component_reference_rejected(self) -> None:
        """One good + one bad reference still fails on the bad one."""
        spec = _make_specification(
            container_overrides=[
                DriverContainerOverrideDoc(component="server", command=True),
                DriverContainerOverrideDoc(component="ghost", args=True),
            ]
        )
        with pytest.raises(
            DriverContainerOverrideDocComponentMismatchError
        ) as exc_info:
            validate_driver_container_override_docs(spec)
        assert exc_info.value.component_name == "ghost"


# ---------------------------------------------------------------------------
# Registration-aborts-on-bad-doc — full DriverSpec parse + cross-field check,
# exactly as ``services/driver/loaders.py`` runs it.
# ---------------------------------------------------------------------------


class TestRegistrationAbortsOnBadDoc:
    @staticmethod
    def _payload(container_overrides: list[dict] | None) -> dict:
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
                "container_overrides": container_overrides,
            },
        }

    def test_well_formed_doc_parses(self) -> None:
        ds = DriverSpec.model_validate(
            self._payload([{"component": "server", "command": True, "args": True}])
        )
        validate_driver_container_override_docs(ds.spec)
        assert ds.spec.container_overrides is not None
        assert len(ds.spec.container_overrides) == 1

    def test_duplicate_component_aborts_pydantic_parse(self) -> None:
        with pytest.raises(ValidationError):
            DriverSpec.model_validate(
                self._payload(
                    [
                        {"component": "server", "command": True},
                        {"component": "server", "args": True},
                    ]
                )
            )

    def test_unknown_component_aborts_at_cross_field_step(self) -> None:
        ds = DriverSpec.model_validate(
            self._payload([{"component": "does-not-exist", "command": True}])
        )
        with pytest.raises(DriverContainerOverrideDocComponentMismatchError):
            validate_driver_container_override_docs(ds.spec)
