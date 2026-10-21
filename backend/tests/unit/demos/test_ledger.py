"""The file of the environments that the record command created on a demo stack."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.demos.ledger import CreatedEnvironments, default_path
from tests.e2e.demos.stack import EnvironmentRecord

STACK_URL = "http://styrmin.local.styrmin.io:8080"


def test_the_file_is_under_the_xdg_state_directory() -> None:
    assert default_path({"XDG_STATE_HOME": "/state"}) == Path(
        "/state/styrmin/demo-environments.json"
    )
    assert (
        default_path({}) == Path.home() / ".local/state/styrmin/demo-environments.json"
    )


def test_remember_and_forget_keep_each_stack_apart(tmp_path) -> None:
    path = tmp_path / "styrmin" / "demo-environments.json"
    local = CreatedEnvironments(path, STACK_URL)
    other = CreatedEnvironments(path, "http://other.test:8080")

    assert "env-1" not in local
    local.remember([EnvironmentRecord("network-lab", "env-1")])
    other.remember([EnvironmentRecord("network-lab", "env-2")])

    assert "env-1" in local
    assert "env-2" not in local
    assert "env-2" in other
    local.forget([EnvironmentRecord("network-lab", "env-1")])
    assert "env-1" not in local
    assert "env-2" in CreatedEnvironments(path, "http://other.test:8080")
    assert [item.name for item in path.parent.iterdir()] == ["demo-environments.json"]


@pytest.mark.parametrize("content", ["not json", '["env-1"]', '{"url": ["env-1"]}'])
def test_a_damaged_file_names_its_path(tmp_path, content: str) -> None:
    path = tmp_path / "demo-environments.json"
    path.write_text(content)

    with pytest.raises(ValueError, match=str(path)):
        _ = "env-1" in CreatedEnvironments(path, STACK_URL)
