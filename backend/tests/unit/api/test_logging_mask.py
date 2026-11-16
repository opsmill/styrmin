"""Unit tests for the masking of the GraphQL request log (FR-029, #573).

``mask_variables`` keeps the ids, the names, the booleans and the nulls of
the variables, and masks every other value, so no password, env var value or
access key reaches the log whatever the variable is called.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.api.logging.mask import MASK_PLACEHOLDER, mask_variables


def test_returns_empty_dict_for_none() -> None:
    assert mask_variables(None) == {}


def test_keeps_ids_names_booleans_and_nulls() -> None:
    deployment_id = str(uuid4())
    original = {
        "deploymentId": deployment_id,
        "userIds": [deployment_id],
        "id": deployment_id,
        "input": {"name": "web", "enabled": True, "image": None},
    }

    assert mask_variables(original) == original


@pytest.mark.parametrize("name", ["password", "newPassword", "currentPassword", "p"])
def test_masks_a_password_in_a_variable_of_any_name(name: str) -> None:
    masked = mask_variables({"u": "alice", name: "FAKE573-var-5555"})

    assert masked == {"u": MASK_PLACEHOLDER, name: MASK_PLACEHOLDER}


def test_masks_env_var_values_and_keeps_their_names() -> None:
    payload = {
        "deploymentId": str(uuid4()),
        "input": {
            "components": [
                {
                    "name": "app",
                    "envVars": [
                        {"name": "APP_ADMIN_PASSWORD", "value": "FAKE573-pw-1111"},
                        {"name": "PLAIN_SETTING", "value": "FAKE573-plain-2222"},
                    ],
                    "replicas": 2,
                }
            ]
        },
    }

    masked = mask_variables(payload)

    component = masked["input"]["components"][0]
    assert component["name"] == "app"
    assert component["envVars"] == [
        {"name": "APP_ADMIN_PASSWORD", "value": MASK_PLACEHOLDER},
        {"name": "PLAIN_SETTING", "value": MASK_PLACEHOLDER},
    ]
    assert component["replicas"] == MASK_PLACEHOLDER


def test_masks_the_keys_of_a_backup_storage_location() -> None:
    masked = mask_variables(
        {
            "name": "garage",
            "accessKeyId": "GK-FAKE573",
            "secretAccessKey": "FAKE573-secret-key",
        }
    )

    assert "FAKE573-secret-key" not in str(masked)
    # The API never returns the access key id, so the log does not show it either.
    assert "GK-FAKE573" not in str(masked)
    assert masked["name"] == "garage"


def test_masks_parameter_values() -> None:
    masked = mask_variables(
        {"parameters": [{"name": "admin_password", "value": "FAKE573-param-pw"}]}
    )

    assert masked == {
        "parameters": [{"name": "admin_password", "value": MASK_PLACEHOLDER}]
    }


def test_does_not_mutate_input() -> None:
    original = {"password": "hunter22!", "input": {"envVars": [{"value": "x"}]}}

    mask_variables(original)

    assert original == {"password": "hunter22!", "input": {"envVars": [{"value": "x"}]}}
