"""The input checks walk lists of nested inputs, which ``UpdateClusterInput`` no longer has (#482)."""

import pytest
from styrmin_sdk import _input_checks  # noqa: PLC2701 — intentionally testing a private helper
from styrmin_sdk.models import SchedulingInput


def test_validate_input_strict_names_an_unknown_key_inside_a_list() -> None:
    with pytest.raises(ValueError, match=r"tolerations\[0\]\.operatr"):
        _input_checks.validate_input_strict(SchedulingInput, {"tolerations": [{"key": "x", "operatr": "Exists"}]})


def test_to_graphql_enum_names_converts_enum_values_inside_a_list() -> None:
    converted = _input_checks.to_graphql_enum_names(
        SchedulingInput,
        {
            "tolerations": [{"key": "dedicated", "operator": "Exists", "effect": "NoSchedule"}],
            "topology_spread_constraints": [
                {"max_skew": 1, "topology_key": "zone", "when_unsatisfiable": "DoNotSchedule"}
            ],
        },
    )

    assert converted["tolerations"] == [{"key": "dedicated", "operator": "EXISTS", "effect": "NO_SCHEDULE"}]
    assert converted["topology_spread_constraints"][0]["when_unsatisfiable"] == "DO_NOT_SCHEDULE"
