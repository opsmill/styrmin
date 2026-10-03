"""Storage and context models for per-component image overrides (018, T014/T015).

``ComponentConfigBlock.image`` re-validates stored references with a placeholder version, so
every path that builds the model (write, read, CRD) raises the typed error.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentImageOverride,
)
from styrmin_backend.context.models.config import ComponentConfigBlock, DeploymentConfig
from styrmin_backend.context.validators import validate_deployment_config
from styrmin_backend.services.image_overrides.exceptions import (
    InvalidImageReferenceError,
)

_TOKEN = "registry.example/acme/simple-app-patched:{{ app.version }}"


def _component_context(**fields: object) -> ComponentContext:
    return ComponentContext(
        name="server",
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(label=LabelIdentifier(root={"app": "server"})),
            container="simple-app",
        ),
        **fields,
    )


class TestComponentConfigBlockImage:
    def test_defaults_to_none(self) -> None:
        assert ComponentConfigBlock().image is None

    def test_token_reference_stored_unsubstituted(self) -> None:
        block = ComponentConfigBlock.model_validate({"image": _TOKEN})
        assert block.image == _TOKEN

    def test_digest_reference_accepted(self) -> None:
        ref = "app@sha256:" + "a" * 64
        assert ComponentConfigBlock(image=ref).image == ref

    @pytest.mark.parametrize(
        ("bad", "reason"),
        [
            ("", "grammar"),
            ("app", "missing_tag_or_digest"),
            ("App:1", "grammar"),
            (" app:1", "grammar"),
            ("app:{{ app.name }}", "template_expression"),
            (123, "grammar"),
        ],
    )
    def test_invalid_reference_raises_typed_error(
        self, bad: object, reason: str
    ) -> None:
        with pytest.raises(InvalidImageReferenceError) as exc:
            ComponentConfigBlock.model_validate({"image": bad})
        assert exc.value.reason == reason

    def test_read_path_surfaces_typed_error(self) -> None:
        """``DeploymentConfig.model_validate`` backs the read/CRD path; the code survives there."""
        with pytest.raises(InvalidImageReferenceError):
            DeploymentConfig.model_validate(
                {"components": {"server": {"image": "app"}}}
            )

    def test_write_path_surfaces_typed_error(self) -> None:
        with pytest.raises(InvalidImageReferenceError):
            validate_deployment_config({"components": {"server": {"image": "App:1"}}})

    def test_model_dump_matches_command_and_args(self) -> None:
        """``image=None`` is dumped like ``command``/``args`` and dropped by ``exclude_none``."""
        block = ComponentConfigBlock(command=["serve"])
        assert block.model_dump() == {
            "env_vars": None,
            "command": ["serve"],
            "args": None,
            "image": None,
        }
        assert block.model_dump(exclude_none=True) == {"command": ["serve"]}

    def test_stored_block_round_trips(self) -> None:
        stored = {"server": {"env_vars": {"X": "1"}, "image": _TOKEN}}
        config = DeploymentConfig.model_validate({"components": stored})
        dumped = config.model_dump(exclude_none=True)
        assert dumped == {"components": stored}
        assert DeploymentConfig.model_validate(dumped) == config

    def test_stored_block_without_image_key_validates(self) -> None:
        config = DeploymentConfig.model_validate(
            {"components": {"server": {"command": ["serve"]}}}
        )
        assert config.components is not None
        assert config.components["server"].image is None


class TestResolvedComponentImageOverride:
    def test_defaults_to_live(self) -> None:
        override = ResolvedComponentImageOverride(reference=_TOKEN)
        assert override.is_orphaned is False

    def test_reference_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ResolvedComponentImageOverride.model_validate({})

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ResolvedComponentImageOverride.model_validate(
                {"reference": _TOKEN, "resolved_reference": "x:1"}
            )


class TestComponentContextImageOverride:
    def test_defaults_to_none(self) -> None:
        assert _component_context().image_override is None

    def test_round_trips_through_stored_context(self) -> None:
        ctx = _component_context(
            image_override=ResolvedComponentImageOverride(reference=_TOKEN)
        )
        restored = ComponentContext.model_validate(ctx.model_dump(mode="json"))
        assert restored.image_override == ResolvedComponentImageOverride(
            reference=_TOKEN
        )

    def test_stored_context_without_key_still_validates(self) -> None:
        """Instance contexts persisted before the field existed keep validating."""
        stored = _component_context().model_dump(mode="json")
        stored.pop("image_override")
        assert ComponentContext.model_validate(stored).image_override is None
