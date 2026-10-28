"""SC-003: ``styrmin-driver check`` rejects each invalid driver with the message of the load.

Each case is an invalid driver of the backend's driver tests, built from the example
``simple-app``. The test loads it with the server's loader and checks it with the SDK's
``run_checks``, and compares the messages after the load's wrapping prefix
(specs/032-styrmin-driver-cli, research R-015).
"""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.exceptions import ServiceError
from styrmin_sdk.driver_format.diagnostics import run_checks

EXAMPLE = Path(__file__).parents[5] / "driver" / "examples" / "simple-app"
WRAPPING_PREFIXES = (
    "Error while deserializing the driver resource: ",
    "The driver resource validation failed: ",
)
MODEL_HEADER = "The driver specification is invalid:\n"


def _component(data: dict, name: str) -> dict:
    return data["spec"]["components"][name]


def _service(data: dict) -> dict:
    return data["spec"]["services"][0]


def _parameters(data: dict, *parameters: dict) -> None:
    data["spec"]["parameters"] = list(parameters)


SPEC_CASES: dict[str, Callable[[dict], None]] = {
    "malformed container": lambda d: _component(d, "server").update(
        container="Simple_App"
    ),
    "singleton with replicas": lambda d: _component(d, "database").update(replicas=3),
    "zero replicas": lambda d: _component(d, "server").update(replicas=0),
    "string replicas": lambda d: _component(d, "server").update(replicas="2"),
    "non-bool singleton": lambda d: _component(d, "server").update(singleton="yes"),
    "removed container_overrides block": lambda d: d["spec"].update(
        container_overrides=[]
    ),
    "unknown spec key": lambda d: d["spec"].update(not_a_spec_key=1),
    "two invalid info fields": lambda d: d["spec"]["info"].update(
        license=1, authors="fatih"
    ),
    "wrong apiVersion": lambda d: d.update(apiVersion="wrong"),
    "wrong kind": lambda d: d.update(kind="wrong"),
    "integer metadata name": lambda d: d["metadata"].update(name=123),
    "integer spec version": lambda d: d["spec"].update(version=123),
    "integer helm location": lambda d: d["spec"]["helm"]["main"].update(location=123),
    "invalid env var name": lambda d: d["spec"]["env_vars"][0].update(name="1BAD"),
    "env var doc of an unknown component": lambda d: d["spec"]["env_vars"][1].update(
        components=["does-not-exist"]
    ),
    "missing action function": lambda d: d["spec"]["actions"][0].update(
        location="actions.py::missing"
    ),
    "enum parameter without values": lambda d: _parameters(
        d, {"name": "mode", "label": "Mode", "kind": "enum"}
    ),
    "parameter default of the wrong type": lambda d: _parameters(
        d, {"name": "size", "label": "Size", "kind": "integer", "default": "big"}
    ),
    "duplicate parameter names": lambda d: _parameters(
        d,
        {"name": "size", "label": "Size", "kind": "integer", "default": 1},
        {"name": "size", "label": "Size", "kind": "integer", "default": 2},
    ),
    "service of an unknown kind": lambda d: _service(d).update(kind="grpc"),
    "service port out of range": lambda d: _service(d).update(port=0),
    "service name that is not a DNS label": lambda d: _service(d).update(name="Web"),
    "duplicate service names": lambda d: d["spec"]["services"].append(
        dict(_service(d))
    ),
    "disk backup without a volume": lambda d: _component(d, "database").update(
        backup={"enabled": True, "kind": "disk"}
    ),
}

FILE_CASES: dict[str, Callable[[Path], None]] = {
    "template syntax error": lambda p: (p / "values.j2.yml").write_text("{{ wrong \n"),
    "retired template filter": lambda p: (p / "values.j2.yml").write_text(
        "a: {{ components | component_command }}\n"
    ),
    "driver spec file that is not YAML": lambda p: (
        p / "driver.styrmin.yml"
    ).write_text("kind: [unclosed\n"),
    "missing driver spec file": lambda p: (p / "driver.styrmin.yml").unlink(),
}


def _expected_messages(load_message: str) -> list[str]:
    for prefix in WRAPPING_PREFIXES:
        load_message = load_message.removeprefix(prefix)
    if load_message.startswith(MODEL_HEADER):
        return [
            line.removeprefix("- ")
            for line in load_message.removeprefix(MODEL_HEADER).splitlines()
        ]
    return [load_message]


def _assert_same_messages(driver: Path) -> None:
    with pytest.raises(ServiceError) as raised:
        get_local_driver_loader(path=str(driver)).load_driver()

    report = run_checks(driver)

    tool_messages = [d.message for d in report.errors]
    for expected in _expected_messages(str(raised.value)):
        assert expected in tool_messages


@pytest.mark.parametrize("change", SPEC_CASES.values(), ids=SPEC_CASES.keys())
def test_check_reports_the_load_message_for_an_invalid_spec(
    tmp_path: Path, change: Callable[[dict], None]
) -> None:
    driver = tmp_path / "driver"
    shutil.copytree(EXAMPLE, driver)
    spec_file = driver / "driver.styrmin.yml"
    data = yaml.safe_load(spec_file.read_text())
    change(data)
    spec_file.write_text(yaml.safe_dump(data, sort_keys=False))

    _assert_same_messages(driver)


@pytest.mark.parametrize("change", FILE_CASES.values(), ids=FILE_CASES.keys())
def test_check_reports_the_load_message_for_an_invalid_file(
    tmp_path: Path, change: Callable[[Path], None]
) -> None:
    driver = tmp_path / "driver"
    shutil.copytree(EXAMPLE, driver)
    change(driver)

    _assert_same_messages(driver)


def test_the_example_driver_loads_and_passes_check() -> None:
    get_local_driver_loader(path=str(EXAMPLE)).load_driver()

    assert run_checks(EXAMPLE).errors == []
