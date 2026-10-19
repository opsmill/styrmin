"""The one-line description of a Kubernetes API answer that is not a success."""

from __future__ import annotations

import json

import pytest

from styrmin_backend.agent.service.kubernetes.utils import describe_api_answer

STATUS_BODY = json.dumps(
    {
        "kind": "Status",
        "status": "Failure",
        "message": 'services "db" is forbidden: cannot create "services"',
        "reason": "Forbidden",
        "code": 403,
    }
)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            STATUS_BODY.encode(),
            'the Kubernetes API answered 403: services "db" is forbidden: '
            'cannot create "services"',
            id="status-bytes",
        ),
        pytest.param(
            STATUS_BODY,
            'the Kubernetes API answered 403: services "db" is forbidden: '
            'cannot create "services"',
            id="status-text",
        ),
        pytest.param(None, "the Kubernetes API answered 403: Forbidden", id="no-body"),
        pytest.param(
            b"<html>forbidden</html>",
            "the Kubernetes API answered 403: Forbidden",
            id="not-json",
        ),
        pytest.param(
            json.dumps({"kind": "Status"}),
            "the Kubernetes API answered 403: Forbidden",
            id="no-message",
        ),
        pytest.param(
            json.dumps(["forbidden"]),
            "the Kubernetes API answered 403: Forbidden",
            id="not-an-object",
        ),
    ],
)
def test_gives_the_status_message_else_the_http_reason(
    body: str | bytes | None, expected: str
) -> None:
    assert describe_api_answer(403, "Forbidden", body) == expected
