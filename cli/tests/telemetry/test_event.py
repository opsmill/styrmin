"""Unit tests for telemetry event building + scrubbing (T007).

Covers the closed-set ``data`` key order, closed-set ``command`` resolution,
canonical long-form ``options`` extraction (deduped + sorted, positionals and
repeat-counts excluded), ``event_id`` composition, coarse environment facts,
and the scrub-by-construction guarantee, including that a ``@file`` option
value is never opened or read during name extraction (FR-007 to FR-013, E1).
"""

from __future__ import annotations

import platform
from importlib.metadata import version
from typing import Annotated

import pytest
from cyclopts import App, Parameter
from styrminctl.cli_commands import app as real_app
from styrminctl.telemetry.event import build_event

_DATA_KEY_ORDER = [
    "event_id",
    "install_id",
    "command",
    "options",
    "outcome",
    "error_category",
    "styrminctl_version",
    "python_version",
    "os_family",
]

_INSTALL_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


@pytest.fixture
def sample_app() -> App:
    """A small Cyclopts app with a short alias, a flag, and a positional."""
    app = App(name="styrminctl")

    @app.command(name="go")
    def go(
        name: str,
        config: Annotated[str, Parameter(name=["--config", "-c"])] = "x",
        wait: bool = False,
    ):
        pass

    # A nested group to exercise space-joined multi-token routes.
    sub = App(name="deployments")

    @sub.command(name="update")
    def update(
        deployment_id: str,
        config: Annotated[str, Parameter(name=["--config"])] = "x",
    ):
        pass

    app.command(sub)
    return app


def test_data_has_exact_closed_key_set_in_order(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        tokens=["go", "myname"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert list(data.keys()) == _DATA_KEY_ORDER


def test_command_resolved_from_route_space_joined(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        tokens=["deployments", "update", "dep-1", "--config", "@/secret.json"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert data["command"] == "deployments update"


def test_event_id_composition(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        tokens=["deployments", "update", "dep-1"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert data["event_id"] == f"{_INSTALL_ID[:8]}-deployments_update"
    assert data["install_id"] == _INSTALL_ID


def test_options_are_canonical_long_names_deduped_sorted(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        # short -c maps to --config; --wait flag; positional excluded; -c repeated
        tokens=["go", "myname", "-c", "v", "--wait", "-c", "v2"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert data["options"] == ["--config", "--wait"]


def test_options_exclude_positionals(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        tokens=["go", "myname"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert data["options"] == []


def test_options_handle_equals_form_without_leaking_value(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        tokens=["go", "myname", "--config=supersecretvalue"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert data["options"] == ["--config"]


def test_environment_facts_are_coarse(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        tokens=["go", "myname"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert data["os_family"] == platform.system()
    assert data["python_version"] == platform.python_version()
    assert data["styrminctl_version"] == version("cli")
    # No kernel string / arch / build detail leaks: os_family is a coarse token
    # (e.g. "Linux"), never the kernel release.
    assert data["os_family"] in {"Linux", "Darwin", "Windows"}


def test_outcome_and_error_category_passthrough(sample_app: App) -> None:
    data = build_event(
        app=sample_app,
        tokens=["go", "myname"],
        install_id=_INSTALL_ID,
        outcome="failure",
        error_category="network",
    )
    assert data["outcome"] == "failure"
    assert data["error_category"] == "network"


def test_no_forbidden_values_with_sensitive_inputs(sample_app: App) -> None:
    secret_token = "tok_abcdef123456"
    deployment_name = "prod-customer-db"
    file_path = "/home/alice/secrets/config.json"
    data = build_event(
        app=sample_app,
        tokens=[
            "deployments",
            "update",
            deployment_name,
            "--config",
            f"@{file_path}",
        ],
        install_id=_INSTALL_ID,
        outcome="failure",
        error_category="auth",
    )
    blob = repr(data)
    for forbidden in (secret_token, deployment_name, file_path, "@" + file_path):
        assert forbidden not in blob


def test_file_option_value_is_never_opened(sample_app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    # E1: extraction must NOT trigger Cyclopts value conversion / @file reads.
    # Make any file open during event building fail loudly so a regression that
    # materialises a ``@file`` value (and thus reads it) is caught immediately.
    opened: list[str] = []

    def _forbidden_open(file: object, *args: object, **kwargs: object) -> object:
        opened.append(str(file))
        raise AssertionError(f"event building must not open files; opened {file!r}")

    monkeypatch.setattr("builtins.open", _forbidden_open)

    build_event(
        app=sample_app,
        tokens=["deployments", "update", "dep-1", "--config", "@/nonexistent/secret.json"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert opened == []


def test_command_in_known_route_set_for_real_app() -> None:
    # The real app's resolved command must be a member of the registered routes.
    data = build_event(
        app=real_app,
        tokens=["deployments", "get", "dep-1"],
        install_id=_INSTALL_ID,
        outcome="success",
        error_category=None,
    )
    assert data["command"] == "deployments get"
