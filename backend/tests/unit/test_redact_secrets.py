"""The forms of secrets that ``redact_secrets`` finds in a log line (#573)."""

from __future__ import annotations

import time

import pytest

from styrmin_backend.redaction import redact_secrets


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("{'APP_ADMIN_PASSWORD': 'pw-1'}", "pw-1"),
        ("erlangCookie: cookie-2", "cookie-2"),
        ("ssh_passphrase=phrase-3", "phrase-3"),
        ('"secretAccessKey": "key-4"', "key-4"),
        ("Authorization: Bearer tok-5", "tok-5"),
        ("postgres://styrmin:pw-6@db:5432/styrmin", "pw-6"),
    ],
)
def test_redact_secrets_finds_the_known_forms(text: str, secret: str) -> None:
    assert secret not in redact_secrets(text)


def test_redact_secrets_keeps_a_value_in_another_form() -> None:
    # Why code must log ids and names, never values.
    assert redact_secrets("{'FOO': 'value-7'}") == "{'FOO': 'value-7'}"


@pytest.mark.parametrize(
    "text",
    [
        "{'APP_ADMIN_PASSWORD': 'correct horse, battery; staple'}",
        '{"password": "correct horse, battery; staple"}',
    ],
)
def test_redact_secrets_replaces_a_quoted_value_whole(text: str) -> None:
    redacted = redact_secrets(text)

    for word in ("correct", "horse", "battery", "staple"):
        assert word not in redacted


def test_redact_secrets_keeps_the_name_of_a_kubernetes_secret() -> None:
    # Log lines name a Secret without ``:`` or ``=`` after the word, so the
    # name stays readable (velero client).
    text = "Created BSL credential Secret velero-bsl-1234"

    assert redact_secrets(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "GET /" + "-".join(["a"] * 8000),
        ".".join(["x"] * 8000),
        "a-a-" * 4000 + "://user:pw@host/",
        "GET /" + "token" * 6400,
    ],
    ids=["hyphens", "dots", "url-scheme", "repeated-keyword"],
)
def test_redact_secrets_takes_linear_time_on_a_long_word(text: str) -> None:
    # Every log line goes through the redaction, including the server's access
    # log, whose request path a client chooses. A pattern that rescans a long
    # ``a-a-a-...`` word from each of its word boundaries took about 5 s here.
    started = time.perf_counter()

    redact_secrets(text)

    assert time.perf_counter() - started < 0.5
