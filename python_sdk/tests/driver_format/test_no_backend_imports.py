"""The driver format code imports nothing of the server (contracts/internal-interfaces.md)."""

import json
import subprocess  # noqa: S404 - spawns a trusted, fixed-argv child interpreter
import sys

FORBIDDEN = ("styrmin_backend", "prefect", "dulwich", "loguru", "sqlmodel", "pydantic_settings")
MODULES = (
    "styrmin_sdk.driver_format.checks",
    "styrmin_sdk.driver_format.cli",
    "styrmin_sdk.driver_format.context",
    "styrmin_sdk.driver_format.context.service_entries",
    "styrmin_sdk.driver_format.diagnostics",
    "styrmin_sdk.driver_format.diff",
    "styrmin_sdk.driver_format.example_context",
    "styrmin_sdk.driver_format.reading.files",
    "styrmin_sdk.driver_format.reading.local",
    "styrmin_sdk.driver_format.rendering",
)


def test_the_driver_format_modules_load_without_server_packages() -> None:
    code = (
        "import importlib, json, sys\n"
        f"for name in {MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no untrusted input
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    loaded = json.loads(result.stdout)

    leaked = [m for m in loaded if m.split(".")[0] in FORBIDDEN]
    assert leaked == []
