"""Printing a context shows the deployment it belongs to, not its values (#573).

Driver actions log ``f"Context: {context}"``; the values template, the
parameters and the env vars of a context can hold passwords.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from tests.helpers.secret_context import TEMPLATE_SECRETS, secret_context


@pytest.mark.parametrize("render", [str, repr])
def test_printing_a_context_shows_no_secret(render) -> None:
    deployment_id = uuid4()
    context = secret_context(deployment_id=deployment_id)

    text = render(context)

    for secret in (
        "FAKE573-env-pw",
        "FAKE573-plain-value",
        "FAKE573-param-pw",
        *TEMPLATE_SECRETS,
    ):
        assert secret not in text
    assert str(deployment_id) in text
    assert "infrahub" in text
    assert "1.11.7" in text


def test_a_printed_context_still_dumps_every_value() -> None:
    # Only the printed form changes: the flows and the CRD read the dump.
    context = secret_context()

    dumped = context.model_dump(mode="json")

    assert dumped["parameters"] == {"admin_password": "FAKE573-param-pw"}
    assert dumped["instance"]["config"]["env_vars"]["PLAIN_SETTING"] == (
        "FAKE573-plain-value"
    )
