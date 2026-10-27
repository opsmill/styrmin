"""Secrets stay out of the logs of every Styrmin process (#573, ADR-016).

Importing ``styrmin_backend`` installs the redaction, as it does in the
server, the agent and every flow run. The tests log the way the flow runs do:
through a Prefect run logger, whose records go to the process output and to
Prefect's log table, and through loguru.
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from loguru import logger
from uvicorn.logging import AccessFormatter

import styrmin_backend  # noqa: F401 - installs the redaction, as in every process

ENV_SECRET = "FAKE573-pw-1111"
TOKEN = "FAKE573-tok-2222"
COOKIE = "FAKE573-cookie-3333"


@pytest.fixture
def flow_run_log() -> Iterator[io.StringIO]:
    """The text that a handler of Prefect's flow-run logger writes."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    run_logger = logging.getLogger("prefect.flow_runs")
    run_logger.addHandler(handler)
    level = run_logger.level
    run_logger.setLevel(logging.DEBUG)
    try:
        yield stream
    finally:
        run_logger.removeHandler(handler)
        run_logger.setLevel(level)


@pytest.fixture
def loguru_log() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler_id = logger.add(stream, level="DEBUG", format="{message}")
    try:
        yield stream
    finally:
        logger.remove(handler_id)


def test_a_flow_run_record_holds_no_env_var_value_named_as_a_secret(
    flow_run_log: io.StringIO,
) -> None:
    env_vars = {"APP_ADMIN_PASSWORD": ENV_SECRET, "API_TOKEN": TOKEN, "PORT": "8080"}

    logging.getLogger("prefect.flow_runs").info(f"Flow-side diff report: {env_vars}")

    text = flow_run_log.getvalue()
    assert ENV_SECRET not in text
    assert TOKEN not in text
    assert "'PORT': '8080'" in text
    assert "<redacted>" in text


def test_a_flow_run_record_holds_no_secret_of_a_values_template(
    flow_run_log: io.StringIO,
) -> None:
    template = (
        f"prefect:\n  password: {ENV_SECRET}\nrabbitmq:\n  erlangCookie: {COOKIE}\n"
    )

    logging.getLogger("prefect.flow_runs").info("Context: values_template=%r", template)

    text = flow_run_log.getvalue()
    assert ENV_SECRET not in text
    assert COOKIE not in text


def test_a_flow_run_traceback_holds_no_secret(flow_run_log: io.StringIO) -> None:
    try:
        raise RuntimeError(f"cannot connect: password={ENV_SECRET}")
    except RuntimeError:
        logging.getLogger("prefect.flow_runs").exception("connection failed")

    text = flow_run_log.getvalue()
    assert "RuntimeError: cannot connect: password=" in text
    assert ENV_SECRET not in text


def test_a_record_without_a_secret_keeps_its_arguments() -> None:
    # uvicorn's access log formatter reads ``record.args``.
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s %s", ("GET", "/health"), None
    )

    assert record.args == ("GET", "/health")
    assert record.getMessage() == "GET /health"


def test_a_loguru_message_holds_no_secret(loguru_log: io.StringIO) -> None:
    logger.info("Raw diffs: {}", {"API_TOKEN": TOKEN, "PORT": "8080"})

    text = loguru_log.getvalue()
    assert TOKEN not in text
    assert "'PORT': '8080'" in text


def test_a_loguru_traceback_shows_no_variable_value(tmp_path: Path) -> None:
    # Loguru's ``diagnose`` prints the value of each variable of a traceback,
    # such as the action token of ``action_api_token`` when its revoke fails.
    # It needs the source lines, so the script runs from a file.
    script = tmp_path / "revoke.py"
    script.write_text(
        "import sys\n"
        "import styrmin_backend\n"
        "from loguru import logger\n"
        "logger.remove()\n"
        "logger.add(sys.stdout, colorize=False)\n"
        "def delete_session(token):\n"
        "    raise RuntimeError('database down')\n"
        "def revoke(token):\n"
        "    delete_session(token)\n"
        "try:\n"
        f"    revoke('{TOKEN}')\n"
        "except RuntimeError:\n"
        "    logger.exception('Could not revoke a driver action token')\n"
    )
    env = {key: value for key, value in os.environ.items() if key != "LOGURU_DIAGNOSE"}

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    assert "RuntimeError: database down" in result.stdout
    assert "delete_session(token)" in result.stdout
    assert TOKEN not in result.stdout.replace(f"revoke('{TOKEN}')", "")


def test_an_access_log_record_with_a_secret_keeps_its_arguments() -> None:
    # uvicorn's access log formatter unpacks five arguments; a record that lost
    # them printed "--- Logging error ---" instead of the request line.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s')
    )
    access_logger = logging.getLogger("test.uvicorn.access")
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    try:
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "10.0.0.1:5000",
            "GET",
            f"/graphql?token={TOKEN}",
            "1.1",
            200,
        )
    finally:
        access_logger.removeHandler(handler)

    assert stream.getvalue() == (
        '10.0.0.1:5000 - "GET /graphql?token=<redacted> HTTP/1.1" 200 OK\n'
    )


def test_a_secret_split_between_format_and_argument_is_redacted(
    flow_run_log: io.StringIO,
) -> None:
    logging.getLogger("prefect.flow_runs").info("password=%s", ENV_SECRET)

    assert ENV_SECRET not in flow_run_log.getvalue()


def test_a_loguru_traceback_holds_no_secret(loguru_log: io.StringIO) -> None:
    # A loguru sink formats the exception itself, after the patcher.
    try:
        raise RuntimeError(f"clone of https://user:{TOKEN}@git.example/x.git failed")
    except RuntimeError:
        logger.exception("Could not load the driver")

    text = loguru_log.getvalue()
    assert "Could not load the driver" in text
    assert "RuntimeError: clone of https://git.example/x.git failed" in text
    assert TOKEN not in text


def test_the_loguru_redaction_does_not_change_the_callers_values(
    loguru_log: io.StringIO,
) -> None:
    body = {"request": {"token": TOKEN}}

    logger.bind(body=body).info("sent")

    assert body == {"request": {"token": TOKEN}}
