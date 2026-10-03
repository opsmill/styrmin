"""Unit tests for ``ContainerEnvPatch`` rendering (017-post-render-env-vars, T006).

Pins the strategic-merge document from contracts/post-render-patch.md and the
critique E5 guarantee that user values stay strings through ``yaml.dump`` and
a YAML parse.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ContainerEnvPatch,
)


def _load(patch: ContainerEnvPatch) -> dict[str, Any]:
    doc = yaml.safe_load(patch.render_value())
    assert isinstance(doc, dict)
    return doc


def _containers(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return doc["spec"]["template"]["spec"]["containers"]


class TestContainerEnvPatchShape:
    def test_renders_strategic_merge_document(self) -> None:
        doc = _load(
            ContainerEnvPatch(
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
        doc = _load(ContainerEnvPatch(container="app", env={"A": "1"}, kind=kind))

        assert doc["kind"] == kind
        assert doc["apiVersion"] == "apps/v1"

    def test_only_the_component_container_is_patched(self) -> None:
        doc = _load(ContainerEnvPatch(container="app", env={"A": "1"}))

        pod_spec = doc["spec"]["template"]["spec"]
        assert set(pod_spec) == {"containers"}
        assert [c["name"] for c in pod_spec["containers"]] == ["app"]

    def test_env_entries_keep_input_order(self) -> None:
        env = {"ZETA": "1", "ALPHA": "2", "MID": "3"}
        doc = _load(ContainerEnvPatch(container="app", env=env))

        assert [e["name"] for e in _containers(doc)[0]["env"]] == list(env)

    def test_every_entry_clears_value_from(self) -> None:
        doc = _load(ContainerEnvPatch(container="app", env={"A": "1", "B": "2"}))

        for entry in _containers(doc)[0]["env"]:
            assert "valueFrom" in entry
            assert entry["valueFrom"] is None


class TestContainerEnvPatchNameOnly:
    """018 contracts/post-render-patch.md: an image-only component gets a name-only merge."""

    def test_default_env_renders_name_only_container(self) -> None:
        doc = _load(ContainerEnvPatch(container="app"))

        assert _containers(doc) == [{"name": "app"}]

    def test_empty_env_omits_env_key(self) -> None:
        rendered = ContainerEnvPatch(container="app", env={}).render_value()

        assert _containers(yaml.safe_load(rendered)) == [{"name": "app"}]
        assert "env" not in rendered


class TestContainerEnvPatchScalarRoundTrip:
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
        doc = _load(ContainerEnvPatch(container="app", env={"VAR": value}))

        loaded = _containers(doc)[0]["env"][0]["value"]
        assert isinstance(loaded, str)
        assert loaded == value
