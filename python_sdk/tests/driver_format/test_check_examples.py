"""SC-001: the example drivers pass ``styrmin-driver check``."""

import pytest

from .conftest import EXAMPLE_NAMES, EXAMPLES

# slurpit's values.j2.yml reads services.slurpit (lines 84 and 89), and the driver declares no
# service, so on a deployment both values render empty. Kept as a known failure until the
# driver is fixed or the decision is taken otherwise (specs/032-styrmin-driver-cli/tasks.md).
KNOWN_FAILURES = {"slurpit"}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            n,
            marks=pytest.mark.xfail(
                strict=True, reason="values.j2.yml reads services.slurpit, which the driver does not declare"
            ),
        )
        if n in KNOWN_FAILURES
        else n
        for n in EXAMPLE_NAMES
    ],
)
def test_example_driver_passes_check(name: str, run_cli) -> None:
    result = run_cli("check", str(EXAMPLES / name))

    assert result.code == 0, result.out
    assert " error: " not in result.out


def test_there_are_eight_example_drivers() -> None:
    assert len(EXAMPLE_NAMES) == 8


@pytest.mark.parametrize("name", ["generic-app", "infrahub-mcp"])
def test_a_parameter_without_default_gets_a_placeholder_warning(name: str, run_cli) -> None:
    result = run_cli("check", str(EXAMPLES / name))

    assert result.out.count("has no default; the example context uses the placeholder") == 1


@pytest.mark.parametrize("name", [n for n in EXAMPLE_NAMES if n != "semaphore"])
def test_a_driver_without_default_version_gets_a_version_warning(name: str, run_cli) -> None:
    result = run_cli("check", str(EXAMPLES / name))

    assert result.out.count("warning: no default_version; the example context uses application version") == 1


def test_semaphore_uses_its_default_version_without_warning(run_cli) -> None:
    result = run_cli("check", str(EXAMPLES / "semaphore"))

    assert result.out == f"{EXAMPLES / 'semaphore'}: no errors\n"
