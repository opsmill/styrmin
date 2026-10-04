"""Unit tests for the component-container guard failure parser and its typed error (018, T005)."""

from __future__ import annotations

import pytest

from styrmin_backend.services.component_container.exceptions import (
    GUARD_KEY_PREFIX,
    ComponentContainerNotFoundError,
    parse_guard_failure,
)

# helm-controller condition message wrapping the error kustomize returns for the guard's remove op.
HELM_CONTROLLER_MESSAGE = (
    "Helm upgrade failed for release styrmin-3f2a9c1e/simple-app-web with chart simple-app@0.1.0: "
    "error while running post render on files: error in remove for path: "
    "'/spec/template/spec/styrmin.io~1component-container~1server~1wrong-name/image': "
    "Unable to remove nonexistent key: image: missing value"
)
# Captured verbatim from `kubectl kustomize` (kustomize v5.7.1) for component "ser~v/er".
KUSTOMIZE_ESCAPED_MESSAGE = (
    "error in remove for path: "
    "'/spec/template/spec/styrmin.io~1component-container~1ser~0v~1er~1wrong-name/image': "
    "Unable to remove nonexistent key: image: missing value"
)


def test_guard_key_prefix_is_json_pointer_escaped() -> None:
    assert GUARD_KEY_PREFIX == "styrmin.io~1component-container~1"


def test_parse_guard_failure_from_helm_controller_message() -> None:
    assert parse_guard_failure(HELM_CONTROLLER_MESSAGE) == ("server", "wrong-name")


def test_parse_guard_failure_unescapes_component_name() -> None:
    assert parse_guard_failure(KUSTOMIZE_ESCAPED_MESSAGE) == ("ser~v/er", "wrong-name")


@pytest.mark.parametrize(
    ("escaped", "component"),
    [
        ("a~1b", "a/b"),
        ("a~0b", "a~b"),
        ("~01", "~1"),
        ("~10", "/0"),
        ("a~1~1b~0", "a//b~"),
    ],
)
def test_parse_guard_failure_unescapes_in_rfc6901_order(
    escaped: str, component: str
) -> None:
    message = f"error in remove for path: '/spec/template/spec/{GUARD_KEY_PREFIX}{escaped}~1main/image': x"
    assert parse_guard_failure(message) == (component, "main")


@pytest.mark.parametrize("component", ["my server", "it's", 'say "hi"', "a b~c/d"])
def test_parse_guard_failure_accepts_free_form_component_names(component: str) -> None:
    escaped = component.replace("~", "~0").replace("/", "~1")
    message = f"error in remove for path: '/spec/template/spec/{GUARD_KEY_PREFIX}{escaped}~1main/image': x"
    assert parse_guard_failure(message) == (component, "main")


def test_parse_guard_failure_in_multiline_message() -> None:
    message = f"reconciliation failed\n\nLast error:\n{HELM_CONTROLLER_MESSAGE}\n"
    assert parse_guard_failure(message) == ("server", "wrong-name")


@pytest.mark.parametrize(
    "message",
    [
        "",
        "Helm upgrade failed: timed out waiting for the condition",
        "error in remove for path: '/spec/template/spec/containers/0/image': Unable to remove nonexistent key",
        # Guard key without the "/image" suffix (a move op), or on another field.
        f"error in move for path: '/spec/template/spec/{GUARD_KEY_PREFIX}server~1main': missing value",
        f"error in move for path: '/spec/template/spec/{GUARD_KEY_PREFIX}server~1main/styrmin-image': x",
        f"error in remove for path: '/spec/template/spec/{GUARD_KEY_PREFIX}server~1main/imagePullPolicy': x",
        # Prefix with only one segment: no container name.
        f"error in remove for path: '/spec/template/spec/{GUARD_KEY_PREFIX}server/image': x",
    ],
)
def test_parse_guard_failure_ignores_unrelated_messages(message: str) -> None:
    assert parse_guard_failure(message) is None


def test_component_container_not_found_error() -> None:
    error = ComponentContainerNotFoundError(
        component_name="server", container="wrong-name"
    )
    assert error.error_code == "COMPONENT_CONTAINER_NOT_FOUND"
    assert error.error_metadata == {
        "component_name": "server",
        "container": "wrong-name",
    }
    assert str(error) == (
        "Component 'server': component container 'wrong-name' was not found in its rendered "
        "workload. Styrmin never adds a container; fix components.server.container in the "
        "driver specification file."
    )


def test_component_container_not_found_error_from_parsed_guard_failure() -> None:
    parsed = parse_guard_failure(HELM_CONTROLLER_MESSAGE)
    assert parsed is not None
    component, container = parsed
    error = ComponentContainerNotFoundError(
        component_name=component, container=container
    )
    assert "'server'" in str(error)
    assert "'wrong-name'" in str(error)
