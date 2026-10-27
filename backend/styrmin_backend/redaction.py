"""Remove secrets from the log records of every Styrmin process.

ADR-016: "Logging credentials is a forbidden operation enforced at the
serializer layer, not at each call site." :func:`install_log_redaction` makes
every record of the standard ``logging`` module and of loguru go through
:func:`redact_secrets` before a handler writes it. Prefect's handlers write
the flow-run logs to the process output and to Prefect's log table, so both
receive the redacted text.

The package's ``__init__`` calls :func:`install_log_redaction`. The server,
the agent, the flow runs that the task worker and the agent start, and the
flow runs of driver actions all import ``styrmin_backend``, so it runs in each
of them.

The patterns find a secret by its form. A secret written in another form,
such as the value of an environment variable named ``FOO``, is kept, so code
must log ids and names, never values. This module imports only the standard
library and loguru, because the package's ``__init__`` imports it.
"""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Iterable
from typing import Any

#: What replaces a secret.
REDACTED = "<redacted>"

#: Keys of loguru's ``extra`` whose value is always replaced, at any depth.
SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "passwordHash",
        "token",
        "raw_token",
        "token_hash",
        "session_token",
        "styrmin_session",
    }
)

# The patterns run on every log line, so each one must take a time linear in
# the length of the line: a request path of the server's access log can be
# 16 KB that a client chose. A pattern that starts at each word boundary of a
# long ``a-a-a-...`` word and scans to its end takes seconds on such a line.

# The user info after the ``://`` of a URL, such as ``https://user:token@host``.
_USER_INFO = re.compile(r"(?<=[A-Za-z0-9+.-])(://)[^/\s]*@")
# ``Bearer <credential>`` or ``Basic <credential>``, as in an Authorization header.
_AUTHORIZATION = re.compile(r"(?i)\b(bearer|basic)(\s+)[^\s\"',;]+")
# A key whose name says it holds a secret, then ``=`` or ``:``, then its value:
# a quoted string whole, with its spaces and commas, or else the text up to the
# first space, quote, comma, semicolon or ``}``. The key starts where a run of
# ``[\w.-]`` characters starts, so each run is scanned once.
_SECRET_FIELD = re.compile(
    r"(?i)(?<![\w.-])([\w.-]*(?:password|passwd|passphrase|secret|token|api[_-]?key"
    r"|private[_-]?key|credential|cookie)[\w.-]*)([\"']?\s*[:=]\s*)"
    r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[\"']?[^\s\"',;}]+)"
)


def _redact_field_value(match: re.Match[str]) -> str:
    value = match.group(3)
    quote = value[0] if value[0] in "\"'" else ""
    closing = quote if quote and len(value) > 1 and value.endswith(quote) else ""
    return f"{match.group(1)}{match.group(2)}{quote}{REDACTED}{closing}"


_installed = False


def redact_user_info(text: str) -> str:
    """Return ``text`` with the user info of every ``scheme://`` URL in it removed.

    For messages and logs: a clone error can repeat the repository URL with
    its user info. An scp-style address such as ``git@host:o/r.git`` has no
    scheme and is kept.

    >>> redact_user_info("https://user:token@host/x.git")
    'https://host/x.git'
    >>> redact_user_info("git@github.com:o/r.git")
    'git@github.com:o/r.git'
    >>> redact_user_info("https://user:token@[bad/x.git")
    'https://[bad/x.git'
    >>> redact_user_info("cannot reach https://u:t@h/x.git or ssh://git@h/y.git")
    'cannot reach https://h/x.git or ssh://h/y.git'
    >>> redact_user_info("file:///srv/a@b")
    'file:///srv/a@b'
    """
    return _USER_INFO.sub(r"\1", text)


def redact_secrets(text: str, secrets: Iterable[str] = ()) -> str:
    """Return ``text`` with the secrets that it may hold replaced by ``REDACTED``.

    Replaces each value of ``secrets``, such as the action token; the user
    info of every ``scheme://`` URL; the credential after ``Bearer`` or
    ``Basic``; and the value after ``=`` or ``:`` of a key whose name contains
    ``password``, ``passwd``, ``passphrase``, ``secret``, ``token``,
    ``api_key``, ``private_key``, ``credential`` or ``cookie``. A quoted value
    is replaced whole; an unquoted value up to the first space, quote, comma,
    semicolon or ``}``. A secret written in any other form is kept.

    >>> redact_secrets("login failed: password=hunter2 for https://u:p@db/x", ["t0k"])
    'login failed: password=<redacted> for https://db/x'
    >>> redact_secrets("STYRMIN_TOKEN is t0k", ["t0k"])
    'STYRMIN_TOKEN is <redacted>'
    >>> redact_secrets('{"api_key": "abc"} Authorization: Bearer xyz')
    '{"api_key": "<redacted>"} Authorization: Bearer <redacted>'
    >>> redact_secrets("{'APP_ADMIN_PASSWORD': 'pw', 'PORT': '8080'} erlangCookie: c")
    "{'APP_ADMIN_PASSWORD': '<redacted>', 'PORT': '8080'} erlangCookie: <redacted>"
    >>> redact_secrets("{'password': 'correct horse, battery'}")
    "{'password': '<redacted>'}"
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    text = redact_user_info(text)
    text = _AUTHORIZATION.sub(rf"\1\2{REDACTED}", text)
    return _SECRET_FIELD.sub(_redact_field_value, text)


def _redact_names(payload: Any) -> Any:  # noqa: ANN401 - any JSON-like value
    """A copy of ``payload`` with the value of every key in ``SENSITIVE_FIELD_NAMES`` replaced.

    Copies the containers, so the dicts that the caller passed to loguru keep
    their values.
    """
    if isinstance(payload, dict):
        return {
            key: REDACTED if key in SENSITIVE_FIELD_NAMES else _redact_names(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_redact_names(item) for item in payload]
    return payload


def _redact_loguru_exception(record: dict[str, Any]) -> None:
    """Move the traceback of ``record`` into its message when the traceback holds a secret.

    A loguru sink formats ``record["exception"]`` itself, after the patcher,
    so the traceback is formatted here, and replaces the exception only when
    :func:`redact_secrets` changes it.
    """
    exception = record.get("exception")
    if exception is None or exception.value is None:
        return
    text = "".join(
        traceback.format_exception(exception.type, exception.value, exception.traceback)
    )
    redacted = redact_secrets(text)
    if redacted != text:
        record["message"] = f"{record['message']}\n{redacted.rstrip()}"
        record["exception"] = None


def redact_loguru_record(record: dict[str, Any]) -> None:
    """Loguru ``patcher`` that removes secrets from a record before any sink writes it.

    Redacts the message text and the traceback with :func:`redact_secrets`,
    and replaces the value of every key of ``record["extra"]`` named in
    ``SENSITIVE_FIELD_NAMES``, at any depth.
    """
    record["message"] = redact_secrets(record["message"])
    _redact_loguru_exception(record)
    extra = record.get("extra")
    if extra is not None:
        for key in list(extra):
            extra[key] = (
                REDACTED if key in SENSITIVE_FIELD_NAMES else _redact_names(extra[key])
            )


def _redacted_argument(argument: object) -> object:
    if isinstance(argument, str):
        return redact_secrets(argument)
    text = str(argument)
    redacted = redact_secrets(text)
    return argument if redacted == text else redacted


def _replace_message(record: logging.LogRecord, redacted: str) -> None:
    """Put the redacted message in ``record``, keeping its arguments when possible.

    Some formatters read ``record.args`` themselves: uvicorn's access log
    formatter unpacks five of them. The arguments are redacted one by one,
    and kept when the message that they make holds nothing left to redact.
    Otherwise, such as when a secret is split between the format string and an
    argument, the record gets the redacted message and no arguments.
    """
    args = record.args
    if isinstance(record.msg, str) and args and isinstance(args, (tuple, dict)):
        new_args = (
            tuple(_redacted_argument(argument) for argument in args)
            if isinstance(args, tuple)
            else {key: _redacted_argument(value) for key, value in args.items()}
        )
        try:
            message = record.msg % new_args
        except Exception:  # noqa: BLE001 - fall back to the flat message below
            message = None
        if message is not None and redact_secrets(message) == message:
            record.args = new_args
            return
    record.msg = redacted
    record.args = None


def redact_log_record(record: logging.LogRecord) -> None:
    """Remove secrets from the message and the traceback of a ``logging`` record.

    Leaves the record as it is when nothing is redacted, so the handlers that
    read ``record.args`` keep working.
    """
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001 - the handler reports a bad format itself
        return
    redacted = redact_secrets(message)
    if redacted != message:
        _replace_message(record, redacted)
    if record.exc_info and not record.exc_text:
        # ``logging.Formatter.format`` uses ``exc_text`` when it is set.
        record.exc_text = redact_secrets(
            logging.Formatter().formatException(record.exc_info)
        )


def install_log_redaction() -> None:
    """Redact every ``logging`` and loguru record of this process. Runs once.

    For ``logging``, wraps the record factory, so the records of every
    logger are redacted whatever the handlers, including the handlers that
    Prefect sets up later. For loguru, sets :func:`redact_loguru_record` as
    the patcher.
    """
    global _installed
    if _installed:
        return
    _installed = True

    make_record = logging.getLogRecordFactory()

    def _redacting_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:  # noqa: ANN401
        record = make_record(*args, **kwargs)
        redact_log_record(record)
        return record

    logging.setLogRecordFactory(_redacting_factory)

    from loguru import logger

    logger.configure(patcher=redact_loguru_record)
