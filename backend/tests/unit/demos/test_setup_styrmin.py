"""The setup demo's registration and the values it types: the same as those of `uv run invoke start`."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from tests.e2e.demos.catalog import DEMOS
from tests.e2e.demos.scenarios import setup_styrmin

TASKS = Path(__file__).resolve().parents[4] / "tasks"
DEMO_URL = "http://styrmin.local.styrmin.io:8080"


def _tasks_utils():
    """Load tasks/utils.py alone; the tasks package itself patches invoke when it is imported."""
    spec = importlib.util.spec_from_file_location("_tasks_utils", TASKS / "utils.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bootstrap_cluster_constants() -> dict[str, object]:
    """Return the entries with a literal value of the cluster configuration in tasks/dev.py's bootstrap."""
    tree = ast.parse((TASKS / "dev.py").read_text())
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_bootstrap_cluster"
    )
    config = next(
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "config"
    )
    assert isinstance(config, ast.Dict)
    constants: dict[str, object] = {}
    for key, value in zip(config.keys, config.values, strict=True):
        assert isinstance(key, ast.Constant)
        assert isinstance(key.value, str)
        try:
            constants[key.value] = ast.literal_eval(value)
        except ValueError:
            continue
    return constants


def _demo_task_constants() -> dict[str, object]:
    tree = ast.parse((TASKS / "demo.py").read_text())
    return {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"DEMO_HOSTNAME", "DEMO_FQDN_SUFFIX", "DEMO_PORT"}
    }


def test_the_setup_demo_is_registered_first() -> None:
    demo = DEMOS[0]

    assert (demo.slug, demo.number) == ("setup", 0)
    assert demo.setup is setup_styrmin.setup
    assert demo.record is setup_styrmin.record


def test_the_cluster_gets_the_configuration_of_the_bootstrap() -> None:
    demo_task = _demo_task_constants()
    url = f"http://{demo_task['DEMO_HOSTNAME']}:{demo_task['DEMO_PORT']}"

    config = setup_styrmin.cluster_config(url)

    assert url == DEMO_URL
    assert config == {
        **_bootstrap_cluster_constants(),
        "fqdn_suffix": demo_task["DEMO_FQDN_SUFFIX"],
        "external_url_scheme": "http",
        "external_url_port": demo_task["DEMO_PORT"],
    }


def test_the_cluster_configuration_follows_the_styrmin_url() -> None:
    config = setup_styrmin.cluster_config("https://styrmin.lab.example.com")

    assert config["fqdn_suffix"] == "lab.example.com"
    assert config["external_url_scheme"] == "https"
    assert "external_url_port" not in config
    with pytest.raises(ValueError, match="has no domain"):
        setup_styrmin.cluster_config("http://localhost:8080")


def test_the_backup_storage_location_gets_the_garage_values_of_the_bootstrap() -> None:
    utils = _tasks_utils()

    assert (
        setup_styrmin.GARAGE_ENDPOINT,
        setup_styrmin.GARAGE_BUCKET,
        setup_styrmin.GARAGE_REGION,
        setup_styrmin.GARAGE_ACCESS_KEY_ID,
        setup_styrmin.GARAGE_SECRET_ACCESS_KEY,
    ) == (
        utils.GARAGE_ENDPOINT,
        utils.GARAGE_BUCKET,
        utils.GARAGE_REGION,
        utils.GARAGE_ACCESS_KEY_ID,
        utils.GARAGE_SECRET_ACCESS_KEY,
    )


def test_the_setup_loads_the_drivers_that_the_bootstrap_loads() -> None:
    tree = ast.parse((TASKS / "dev.py").read_text())
    bundled = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "BUNDLED_DRIVERS"
        and node.value is not None
    )

    assert {
        setup_styrmin.INFRAHUB_DRIVER_PATH,
        setup_styrmin.SEMAPHORE_DRIVER_PATH,
    } == {f"/styrmin/drivers/{name}" for name in bundled}
