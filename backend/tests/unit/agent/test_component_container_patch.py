"""Unit tests for ``ComponentContainerPatch`` rendering (018-component-image-overrides, T006).

Pins the JSON6902 op lists from contracts/post-render-patch.md: the component container is moved to
a guard key naming the component and the container, its ``image`` is removed (the guard) and set
or restored, then it is moved back to ``containers/0``.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ComponentContainerPatch,
)
from styrmin_backend.services.component_container.exceptions import (
    GUARD_KEY_PREFIX,
    parse_guard_failure,
)

FIRST = "/spec/template/spec/containers/0"
GUARD = "/spec/template/spec/styrmin.io~1component-container~1server~1simple-app"
DIGEST = "sha256:487d074cafebf49cceed5d20c2a33529af08d8e0df76c86c0b9398e23dd2cf37"


def _ops(patch: ComponentContainerPatch) -> list[dict[str, Any]]:
    ops = yaml.safe_load(patch.render_value())
    assert isinstance(ops, list)
    return ops


class TestImageVariant:
    def test_renders_exact_op_list(self) -> None:
        patch = ComponentContainerPatch(
            component="server",
            container="simple-app",
            image="registry.example/acme/simple-app-patched:0.1.0",
        )

        assert _ops(patch) == [
            {"op": "move", "from": FIRST, "path": GUARD},
            {"op": "remove", "path": f"{GUARD}/image"},
            {
                "op": "add",
                "path": f"{GUARD}/image",
                "value": "registry.example/acme/simple-app-patched:0.1.0",
            },
            {"op": "move", "from": GUARD, "path": FIRST},
        ]

    def test_renders_through_yaml_dump(self) -> None:
        patch = ComponentContainerPatch(
            component="server", container="simple-app", image="app:1"
        )

        assert patch.render_value() == yaml.dump(
            _ops(patch), default_flow_style=False, sort_keys=False
        )

    @pytest.mark.parametrize(
        "reference",
        [
            f"[::1]:5000/a.b_c__d-e--f/g:t_1.2-3@{DIGEST}",
            f"registry-1.example.com:443/acme/my__app.x-y:v1.0_rc-2@{DIGEST}",
            "localhost:5000/app:v1",
            "app:true",
            "app:1.0",
            "x" * 255 + ":" + "t" * 128,
        ],
    )
    def test_reference_round_trips_as_string(self, reference: str) -> None:
        patch = ComponentContainerPatch(
            component="server", container="simple-app", image=reference
        )

        value = _ops(patch)[2]["value"]
        assert isinstance(value, str)
        assert value == reference


class TestEnvOnlyVariant:
    def test_renders_exact_op_list(self) -> None:
        patch = ComponentContainerPatch(component="server", container="simple-app")

        assert _ops(patch) == [
            {"op": "move", "from": FIRST, "path": GUARD},
            {"op": "copy", "from": f"{GUARD}/image", "path": f"{GUARD}/styrmin-image"},
            {"op": "remove", "path": f"{GUARD}/image"},
            {"op": "move", "from": f"{GUARD}/styrmin-image", "path": f"{GUARD}/image"},
            {"op": "move", "from": GUARD, "path": FIRST},
        ]

    def test_image_none_is_the_default(self) -> None:
        explicit = ComponentContainerPatch(
            component="server", container="simple-app", image=None
        )
        default = ComponentContainerPatch(component="server", container="simple-app")

        assert explicit.render_value() == default.render_value()


class TestGuardKey:
    @pytest.mark.parametrize(
        ("component", "escaped"),
        [
            ("server", "server"),
            ("a/b", "a~1b"),
            ("a~b", "a~0b"),
            ("~1", "~01"),
            ("/0", "~10"),
            ("ser~v/er", "ser~0v~1er"),
        ],
    )
    def test_component_name_is_json_pointer_escaped(
        self, component: str, escaped: str
    ) -> None:
        patch = ComponentContainerPatch(
            component=component, container="simple-app", image="app:1"
        )
        guard = f"/spec/template/spec/{GUARD_KEY_PREFIX}{escaped}~1simple-app"

        ops = _ops(patch)
        assert ops[0]["path"] == guard
        assert ops[1]["path"] == f"{guard}/image"
        assert ops[-1]["from"] == guard

    @pytest.mark.parametrize("component", ["server", "a/b", "a~b", "~1", "ser~v/er"])
    def test_guard_path_round_trips_through_parser(self, component: str) -> None:
        patch = ComponentContainerPatch(component=component, container="simple-app")
        remove_path = _ops(patch)[2]["path"]
        message = (
            f"error in remove for path: '{remove_path}': "
            "Unable to remove nonexistent key: image: missing value"
        )

        assert parse_guard_failure(message) == (component, "simple-app")

    @pytest.mark.parametrize("kind", ["Deployment", "StatefulSet"])
    def test_kind_does_not_change_the_op_list(self, kind: str) -> None:
        patch = ComponentContainerPatch(
            component="server", container="simple-app", image="app:1", kind=kind
        )
        baseline = ComponentContainerPatch(
            component="server", container="simple-app", image="app:1"
        )

        assert patch.kind == kind
        assert patch.render_value() == baseline.render_value()
