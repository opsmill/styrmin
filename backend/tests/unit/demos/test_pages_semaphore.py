"""The pure helpers of the Semaphore page object: log cleaning and the task status check."""

from __future__ import annotations

import pytest

from tests.e2e.demos.pages.semaphore import check_task_status, strip_ansi
from tests.e2e.drivers.errors import ScenarioActionError


def test_strip_ansi_removes_colour_and_cursor_codes_and_keeps_the_text() -> None:
    log = (
        "\x1b[0;32mok: [sw1] => {\x1b[0m\n"
        "\x1b[1;35m[WARNING]: no hosts\x1b[0m\n"
        "\x1b[2K\x1b[?25lDevices in the inventory: 2\x1b[?25h\n"
    )

    assert (
        strip_ansi(log)
        == "ok: [sw1] => {\n[WARNING]: no hosts\nDevices in the inventory: 2\n"
    )


def test_strip_ansi_leaves_a_log_without_codes_unchanged() -> None:
    log = "PLAY [List the network devices] ****\nskipping: no hosts matched\n"

    assert strip_ansi(log) == log


def test_check_task_status_accepts_success() -> None:
    check_task_status(" Success ", "PLAY RECAP\n")


@pytest.mark.parametrize("status", ["Failed", "Stopped"])
def test_check_task_status_raises_with_the_last_lines_of_the_log(status: str) -> None:
    log = "\n\n".join(f"line {number}" for number in range(1, 13)) + "\n\n"

    with pytest.raises(ScenarioActionError) as raised:
        check_task_status(status, log)

    message = str(raised.value)
    assert f"status {status!r}" in message
    assert message.endswith("\n".join(f"line {number}" for number in range(3, 13)))
    assert "line 2\n" not in message
