"""Unit tests for ``ContainerMergePatch`` rendering (017 T006, 022 T004).

Pins the strategic-merge document from 022 contracts/post-render-patch.md: env
entries, ``command`` and ``args`` on the named container, each only when set.
User values stay strings through ``yaml.dump`` and a YAML parse (017 critique
E5), and a value cannot add patch operations (022 critique E3).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ContainerMergePatch,
)


def _load(patch: ContainerMergePatch) -> dict[str, Any]:
    doc = yaml.safe_load(patch.render_value())
    assert isinstance(doc, dict)
    return doc


def _containers(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return doc["spec"]["template"]["spec"]["containers"]


class TestContainerMergePatchShape:
    def test_renders_strategic_merge_document(self) -> None:
        doc = _load(
            ContainerMergePatch(
                container="prefect-server",
                env={"LOG_LEVEL": "debug", "PROMETHEUS_MULTIPROC_DIR": "/data"},
            )
        )

        assert doc["apiVersion"] == "apps/v1"
        assert doc["kind"] == "Deployment"
        assert doc["metadata"] == {"name": "any"}
        assert _containers(doc) == [
            {
                "name": "prefect-server",
                "env": [
                    {"name": "LOG_LEVEL", "value": "debug", "valueFrom": None},
                    {
                        "name": "PROMETHEUS_MULTIPROC_DIR",
                        "value": "/data",
                        "valueFrom": None,
                    },
                ],
            }
        ]

    @pytest.mark.parametrize("kind", ["Deployment", "StatefulSet"])
    def test_kind_is_rendered_as_given(self, kind: str) -> None:
        doc = _load(ContainerMergePatch(container="app", env={"A": "1"}, kind=kind))

        assert doc["kind"] == kind
        assert doc["apiVersion"] == "apps/v1"

    def test_only_the_component_container_is_patched(self) -> None:
        doc = _load(ContainerMergePatch(container="app", env={"A": "1"}))

        pod_spec = doc["spec"]["template"]["spec"]
        assert set(pod_spec) == {"containers"}
        assert [c["name"] for c in pod_spec["containers"]] == ["app"]

    def test_env_entries_keep_input_order(self) -> None:
        env = {"ZETA": "1", "ALPHA": "2", "MID": "3"}
        doc = _load(ContainerMergePatch(container="app", env=env))

        assert [e["name"] for e in _containers(doc)[0]["env"]] == list(env)

    def test_every_entry_clears_value_from(self) -> None:
        doc = _load(ContainerMergePatch(container="app", env={"A": "1", "B": "2"}))

        for entry in _containers(doc)[0]["env"]:
            assert "valueFrom" in entry
            assert entry["valueFrom"] is None


class TestContainerMergePatchNameOnly:
    """018 contracts/post-render-patch.md: an image-only component gets a name-only merge."""

    def test_default_env_renders_name_only_container(self) -> None:
        doc = _load(ContainerMergePatch(container="app"))

        assert _containers(doc) == [{"name": "app"}]

    def test_empty_env_omits_env_key(self) -> None:
        rendered = ContainerMergePatch(container="app", env={}).render_value()

        assert _containers(yaml.safe_load(rendered)) == [{"name": "app"}]
        assert "env" not in rendered


class TestContainerMergePatchScalarRoundTrip:
    """Critique E5: YAML-significant scalars must come back as strings."""

    @pytest.mark.parametrize(
        "value",
        [
            "true",
            "false",
            "null",
            "~",
            "0123",
            "42",
            "1.5",
            "",
            "line one\nline two\n",
            "$(OTHER)",
            "key: value # not a comment",
            "x" * 200 + " with spaces " + "y" * 200,
        ],
    )
    def test_value_round_trips_as_string(self, value: str) -> None:
        doc = _load(ContainerMergePatch(container="app", env={"VAR": value}))

        loaded = _containers(doc)[0]["env"][0]["value"]
        assert isinstance(loaded, str)
        assert loaded == value


class TestContainerMergePatchCommandArgs:
    """022 contracts/post-render-patch.md: ``command`` and ``args`` only when set."""

    def test_command_only(self) -> None:
        doc = _load(ContainerMergePatch(container="app", command=["/bin/sh", "-c"]))

        assert _containers(doc) == [{"name": "app", "command": ["/bin/sh", "-c"]}]

    def test_args_only(self) -> None:
        doc = _load(ContainerMergePatch(container="app", args=["--log-level", "debug"]))

        assert _containers(doc) == [{"name": "app", "args": ["--log-level", "debug"]}]

    def test_command_and_args_with_env(self) -> None:
        doc = _load(
            ContainerMergePatch(
                container="app",
                env={"LOG_LEVEL": "debug"},
                command=["/bin/sh", "-c"],
                args=["run"],
                kind="StatefulSet",
            )
        )

        assert doc["kind"] == "StatefulSet"
        assert _containers(doc) == [
            {
                "name": "app",
                "env": [{"name": "LOG_LEVEL", "value": "debug", "valueFrom": None}],
                "command": ["/bin/sh", "-c"],
                "args": ["run"],
            }
        ]

    def test_neither_renders_the_same_name_only_document(self) -> None:
        explicit = ContainerMergePatch(container="app", command=None, args=None)

        assert (
            explicit.render_value()
            == ContainerMergePatch(container="app").render_value()
        )
        assert _containers(_load(explicit)) == [{"name": "app"}]
        assert "command" not in explicit.render_value()
        assert "args" not in explicit.render_value()

    @pytest.mark.parametrize("value", ["yes", "8000", "", "null", "$(HOME)"])
    def test_value_round_trips_as_the_same_string(self, value: str) -> None:
        doc = _load(ContainerMergePatch(container="app", command=[value], args=[value]))

        container = _containers(doc)[0]
        for field in ("command", "args"):
            assert container[field] == [value]
            assert isinstance(container[field][0], str)

    def test_value_with_patch_operation_text_stays_one_element(self) -> None:
        value = "x\n- op: remove\n  path: /spec"
        rendered = ContainerMergePatch(
            container="app", command=[value], args=[value]
        ).render_value()

        container = _containers(yaml.safe_load(rendered))[0]
        assert container["command"] == [value]
        assert container["args"] == [value]
        assert set(container) == {"name", "command", "args"}
