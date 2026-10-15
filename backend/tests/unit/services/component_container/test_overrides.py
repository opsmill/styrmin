"""Unit tests for the component-container override rule (022 research D-002, T006).

``override_applies`` is the single rule; ``applicable_overrides`` collects the env vars, image,
``command`` and ``args`` that pass it for one component.
"""

from __future__ import annotations

import pytest

from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentContainerOverride,
    ResolvedComponentEnvVars,
    ResolvedComponentImageOverride,
)
from styrmin_backend.services.component_container.overrides import (
    ApplicableOverrides,
    applicable_overrides,
    override_applies,
)
from styrmin_backend.services.image_overrides.exceptions import (
    InvalidImageReferenceError,
)

_PATCHED = "registry.example/acme/simple-app-patched:0.1.0"


def _component(  # noqa: PLR0913
    *,
    container: str | None = "app",
    env_vars: dict[str, str] | None = None,
    env_orphaned: bool = False,
    image: str | None = None,
    image_orphaned: bool = False,
    command: list[str] | None = None,
    args: list[str] | None = None,
    container_orphaned: bool = False,
) -> ComponentContext:
    has_container_override = command is not None or args is not None
    return ComponentContext(
        name="server",
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": "server"})
            ),
            container=container,
        ),
        env_vars=(
            ResolvedComponentEnvVars(config=env_vars, is_orphaned=env_orphaned)
            if env_vars is not None
            else None
        ),
        image_override=(
            ResolvedComponentImageOverride(reference=image, is_orphaned=image_orphaned)
            if image is not None
            else None
        ),
        container_override=(
            ResolvedComponentContainerOverride(
                command=command, args=args, is_orphaned=container_orphaned
            )
            if has_container_override or container_orphaned
            else None
        ),
    )


def _applicable(
    component: ComponentContext, version: str = "1.0.0"
) -> ApplicableOverrides:
    return applicable_overrides("server", component, version)


class TestOverrideApplies:
    @pytest.mark.parametrize(
        ("container", "is_orphaned", "expected"),
        [
            ("app", False, True),
            ("app", True, False),
            (None, False, False),
            (None, True, False),
        ],
    )
    def test_truth_table(
        self, container: str | None, is_orphaned: bool, expected: bool
    ) -> None:
        assert override_applies(container, is_orphaned) is expected


class TestApplicableOverrides:
    def test_env_applies(self) -> None:
        result = _applicable(_component(env_vars={"LOG_LEVEL": "debug"}))

        assert result == ApplicableOverrides(env={"LOG_LEVEL": "debug"})

    def test_image_applies(self) -> None:
        result = _applicable(_component(image=_PATCHED))

        assert result == ApplicableOverrides(image=_PATCHED)

    def test_command_applies(self) -> None:
        result = _applicable(_component(command=["/bin/sh", "-c"]))

        assert result == ApplicableOverrides(command=["/bin/sh", "-c"])

    def test_args_applies(self) -> None:
        result = _applicable(_component(args=["--log-level", "debug"]))

        assert result == ApplicableOverrides(args=["--log-level", "debug"])

    def test_all_four_apply_together(self) -> None:
        result = _applicable(
            _component(
                env_vars={"A": "1"}, image=_PATCHED, command=["run"], args=["--x"]
            )
        )

        assert result == ApplicableOverrides(
            env={"A": "1"}, image=_PATCHED, command=["run"], args=["--x"]
        )
        assert result.is_empty is False

    def test_no_container_applies_nothing(self) -> None:
        result = _applicable(
            _component(
                container=None,
                env_vars={"A": "1"},
                image=_PATCHED,
                command=["run"],
                args=["--x"],
            )
        )

        assert result == ApplicableOverrides()
        assert result.is_empty is True

    def test_orphaned_env_is_not_applied(self) -> None:
        result = _applicable(_component(env_vars={"A": "1"}, env_orphaned=True))

        assert result.is_empty is True

    def test_orphaned_image_is_not_applied(self) -> None:
        result = _applicable(_component(image=_PATCHED, image_orphaned=True))

        assert result.is_empty is True

    def test_orphaned_container_override_is_not_applied(self) -> None:
        result = _applicable(
            _component(command=["run"], args=["--x"], container_orphaned=True)
        )

        assert result.is_empty is True

    def test_each_orphan_flag_only_drops_its_own_override(self) -> None:
        result = _applicable(
            _component(
                env_vars={"A": "1"},
                image=_PATCHED,
                image_orphaned=True,
                command=["run"],
            )
        )

        assert result == ApplicableOverrides(env={"A": "1"}, command=["run"])

    def test_result_does_not_share_lists_with_the_context(self) -> None:
        component = _component(env_vars={"A": "1"}, command=["run"], args=["--x"])

        result = _applicable(component)
        assert result.command is not None and result.args is not None
        result.env["B"] = "2"
        result.command.append("more")
        result.args.append("more")

        assert component.env_vars is not None
        assert component.env_vars.config == {"A": "1"}
        assert component.container_override is not None
        assert component.container_override.command == ["run"]
        assert component.container_override.args == ["--x"]


class TestIsEmpty:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            (ApplicableOverrides(), True),
            (ApplicableOverrides(env={}), True),
            (ApplicableOverrides(env={"A": "1"}), False),
            (ApplicableOverrides(image=_PATCHED), False),
            (ApplicableOverrides(command=["run"]), False),
            (ApplicableOverrides(args=["--x"]), False),
        ],
        ids=["default", "empty-env", "env", "image", "command", "args"],
    )
    def test_true_only_when_all_four_are_empty(
        self, overrides: ApplicableOverrides, expected: bool
    ) -> None:
        assert overrides.is_empty is expected


class TestImageReference:
    def test_app_version_token_is_substituted(self) -> None:
        result = _applicable(
            _component(image="registry.example/acme/app:{{ app.version }}"),
            version="0.2.0",
        )

        assert result.image == "registry.example/acme/app:0.2.0"

    def test_invalid_after_substitution_raises_typed_error(self) -> None:
        with pytest.raises(InvalidImageReferenceError) as excinfo:
            _applicable(
                _component(image="app:{{ app.version }}"), version="1.0.0+build"
            )

        assert excinfo.value.error_code == "INVALID_IMAGE_REFERENCE"
        assert excinfo.value.error_metadata == {
            "component_name": "server",
            "reference": "app:{{ app.version }}",
            "reason": "after_substitution",
            "application_version": "1.0.0+build",
        }

    def test_image_without_container_is_not_validated(self) -> None:
        result = _applicable(
            _component(container=None, image="app:{{ app.version }}"),
            version="1.0.0+build",
        )

        assert result.image is None

    def test_orphaned_image_is_not_validated(self) -> None:
        result = _applicable(
            _component(image="app:{{ app.version }}", image_orphaned=True),
            version="1.0.0+build",
        )

        assert result.image is None
