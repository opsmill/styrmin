"""Unit tests for the loguru redaction patcher."""

from __future__ import annotations

import io

from loguru import logger

from styrmin_backend.server.logging import REDACTED, redact


def _attach_capture_sink() -> tuple[io.StringIO, int]:
    sink = io.StringIO()
    logger.remove()
    logger.configure(patcher=redact)
    handler_id = logger.add(sink, level="INFO", format="{message} | {extra}")
    return sink, handler_id


def test_password_hash_redacted_in_extra() -> None:
    sink, handler_id = _attach_capture_sink()
    try:
        secret = "argon2id$v=19$m=19456,t=2,p=1$THISISSECRET"
        logger.bind(password_hash=secret).info("authenticating")
        contents = sink.getvalue()
        assert secret not in contents
        assert REDACTED in contents
    finally:
        logger.remove(handler_id)


def test_session_token_redacted_in_extra() -> None:
    sink, handler_id = _attach_capture_sink()
    try:
        secret = "ABCDEF1234567890URLSAFETOKEN"
        logger.bind(token=secret, styrmin_session=secret).info("session ready")
        contents = sink.getvalue()
        assert secret not in contents
        assert REDACTED in contents
    finally:
        logger.remove(handler_id)


def test_password_redacted_in_nested_extra() -> None:
    sink, handler_id = _attach_capture_sink()
    try:
        secret = "supersecret-plaintext"
        logger.bind(payload={"username": "alice", "password": secret}).info(
            "login attempt"
        )
        contents = sink.getvalue()
        assert secret not in contents
        assert REDACTED in contents
        assert "alice" in contents
    finally:
        logger.remove(handler_id)


def test_unrelated_field_not_redacted() -> None:
    sink, handler_id = _attach_capture_sink()
    try:
        logger.bind(username="alice").info("hello")
        contents = sink.getvalue()
        assert "alice" in contents
    finally:
        logger.remove(handler_id)
