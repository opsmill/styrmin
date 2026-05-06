"""Unit tests for the env vars validator (008-deployment-env-vars, T017).

Covers FR-006..FR-009 plus the FR-011 risky-name soft warning. These rules
run in two places (the GraphQL mutation boundary and the Pydantic field
validators on :class:`EnvironmentConfig` / :class:`DeploymentConfig`), so the
tests target the validator module directly rather than through Pydantic to
keep the failure surface narrow.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from loguru import logger

from styrmin_backend.services.env_vars.exceptions import (
    DuplicateEnvVarNameError,
    EnvVarSizeLimitExceededError,
    InvalidEnvVarNameError,
)
from styrmin_backend.services.env_vars.validator import (
    PER_SCOPE_BYTE_CAP,
    PER_SCOPE_ENTRY_CAP,
    PER_VALUE_BYTE_CAP,
    validate_env_var_name,
    validate_env_var_value,
    validate_env_vars_dict,
    validate_env_vars_input_list,
)


@pytest.fixture
def loguru_messages() -> Iterator[list[str]]:
    """Capture loguru log records into a list for the duration of the test.

    The project uses loguru, which does not propagate to the stdlib ``logging``
    module by default, so pytest's ``caplog`` does not see its messages. We
    install a sink-into-list, yield the list, and remove the sink in teardown.
    """
    captured: list[str] = []

    def _sink(message: Any) -> None:
        captured.append(message.record["message"])

    sink_id = logger.add(_sink, level="WARNING")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


class TestValidateEnvVarName:
    @pytest.mark.parametrize(
        "name",
        [
            "FOO",
            "foo",
            "_foo",
            "FOO_BAR",
            "F",
            "_",
            "foo123",
            "FOO_BAR_BAZ_99",
        ],
    )
    def test_accepts_valid_names(self, name: str) -> None:
        validate_env_var_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "1FOO",  # leading digit
            "FOO-BAR",  # hyphen
            "FOO BAR",  # space
            "FOO.BAR",  # dot
            "FOO/BAR",  # slash
            "$FOO",  # symbol
            "FÖO",  # non-ASCII
            "foo bar",
        ],
    )
    def test_rejects_invalid_names(self, name: str) -> None:
        with pytest.raises(InvalidEnvVarNameError) as exc:
            validate_env_var_name(name)
        assert exc.value.error_metadata["name"] == name

    @pytest.mark.parametrize(
        "name",
        [
            "PATH",
            "LD_LIBRARY_PATH",
            "LD_PRELOAD",
            "PYTHONPATH",
            "RUBYLIB",
            "NODE_PATH",
            "JAVA_TOOL_OPTIONS",
        ],
    )
    def test_risky_names_log_warning(
        self, name: str, loguru_messages: list[str]
    ) -> None:
        validate_env_var_name(name, scope="deployment")
        # Names are accepted, not rejected (FR-011: no blocklist).
        assert any("env_var_potentially_risky_name" in m for m in loguru_messages), (
            f"expected risky-name warning for {name!r}, got {loguru_messages!r}"
        )

    def test_non_risky_name_does_not_warn(self, loguru_messages: list[str]) -> None:
        validate_env_var_name("LOG_LEVEL", scope="deployment")
        assert not any("env_var_potentially_risky_name" in m for m in loguru_messages)


class TestValidateEnvVarValue:
    def test_empty_value_accepted(self) -> None:
        validate_env_var_value("FOO", "")

    def test_at_cap_accepted(self) -> None:
        validate_env_var_value("FOO", "x" * PER_VALUE_BYTE_CAP)

    def test_one_byte_over_rejected(self) -> None:
        with pytest.raises(EnvVarSizeLimitExceededError) as exc:
            validate_env_var_value("FOO", "x" * (PER_VALUE_BYTE_CAP + 1))
        assert exc.value.error_metadata["name"] == "FOO"
        assert exc.value.error_metadata["bytes"] == PER_VALUE_BYTE_CAP + 1
        assert exc.value.error_metadata["cap"] == PER_VALUE_BYTE_CAP

    def test_multibyte_chars_count_utf8_bytes(self) -> None:
        # A 3-byte UTF-8 char is 3 bytes per copy. (cap // 3) copies = under
        # the cap, ((cap // 3) + 1) copies overshoot.
        char = "€"  # 3 bytes UTF-8
        under = char * (PER_VALUE_BYTE_CAP // 3)
        validate_env_var_value("FOO", under)
        over = char * (PER_VALUE_BYTE_CAP // 3 + 1)
        with pytest.raises(EnvVarSizeLimitExceededError):
            validate_env_var_value("FOO", over)


class TestValidateEnvVarsDict:
    def test_empty_dict_accepted(self) -> None:
        result = validate_env_vars_dict("environment", {})
        assert result == {}

    def test_returns_fresh_copy(self) -> None:
        original = {"FOO": "bar"}
        result = validate_env_vars_dict("deployment", original)
        assert result == original
        assert result is not original  # callers can mutate without aliasing

    def test_at_entry_cap_accepted(self) -> None:
        mapping = {f"K{i}": "v" for i in range(PER_SCOPE_ENTRY_CAP)}
        validate_env_vars_dict("environment", mapping)

    def test_one_entry_over_cap_rejected(self) -> None:
        mapping = {f"K{i}": "v" for i in range(PER_SCOPE_ENTRY_CAP + 1)}
        with pytest.raises(EnvVarSizeLimitExceededError) as exc:
            validate_env_vars_dict("environment", mapping)
        assert exc.value.error_metadata["entries"] == PER_SCOPE_ENTRY_CAP + 1
        assert exc.value.error_metadata["cap"] == PER_SCOPE_ENTRY_CAP
        assert exc.value.error_metadata["scope"] == "environment"

    def test_at_byte_cap_accepted(self) -> None:
        # Construct a payload whose UTF-8 sum lands exactly on the per-scope
        # cap, while keeping each individual value under the per-value cap.
        # Five keys of 4-byte names + values just under 64 KiB each:
        # 5 * 4 = 20 bytes of names + 5 * (PER_VALUE_BYTE_CAP - 4) = exactly
        # PER_SCOPE_BYTE_CAP = 5 * PER_VALUE_BYTE_CAP = 327680 — too big. So
        # fill the cap with smaller values instead. We aim for total ==
        # PER_SCOPE_BYTE_CAP via key+value bytes.
        target = PER_SCOPE_BYTE_CAP
        # Use 8 entries each ~32 KiB (well under per-value cap of 64 KiB):
        per_value = (target // 8) - 4  # leave ~4 bytes per entry for the key
        mapping = {f"K{i:03d}": "x" * per_value for i in range(8)}
        # Compute actual total to confirm we're at-or-under the cap.
        total = sum(len(k.encode()) + len(v.encode()) for k, v in mapping.items())
        assert total <= PER_SCOPE_BYTE_CAP, total
        validate_env_vars_dict("deployment", mapping)

    def test_one_byte_over_rejected(self) -> None:
        # Per-scope cap (256 KiB) is bigger than per-value cap (64 KiB), so
        # build the over-cap payload from many under-per-value-cap entries.
        per_entry_value = "x" * (PER_VALUE_BYTE_CAP - 1)  # 65535 bytes value
        # entry_bytes ≈ len("Knn") + 65535. 5 such entries already exceed
        # 256 KiB worth of bytes; we just need to land just over the cap.
        mapping: dict[str, str] = {}
        total = 0
        idx = 0
        # Fill until we cross the cap.
        while total <= PER_SCOPE_BYTE_CAP:
            key = f"K{idx:03d}"
            mapping[key] = per_entry_value
            total += len(key.encode("utf-8")) + len(per_entry_value.encode("utf-8"))
            idx += 1
        with pytest.raises(EnvVarSizeLimitExceededError) as exc:
            validate_env_vars_dict("deployment", mapping)
        assert exc.value.error_metadata["scope"] == "deployment"
        assert exc.value.error_metadata["bytes"] > PER_SCOPE_BYTE_CAP
        assert exc.value.error_metadata["cap"] == PER_SCOPE_BYTE_CAP

    def test_invalid_name_in_dict_rejected(self) -> None:
        with pytest.raises(InvalidEnvVarNameError):
            validate_env_vars_dict("deployment", {"1BAD": "v"})


class TestValidateEnvVarsInputList:
    def test_tuples_accepted(self) -> None:
        result = validate_env_vars_input_list(
            [("FOO", "1"), ("BAR", "2")],
            scope="deployment",
        )
        assert result == {"FOO": "1", "BAR": "2"}

    def test_mappings_accepted(self) -> None:
        result = validate_env_vars_input_list(
            [{"name": "FOO", "value": "1"}, {"name": "BAR", "value": "2"}],
            scope="deployment",
        )
        assert result == {"FOO": "1", "BAR": "2"}

    def test_objects_with_attrs_accepted(self) -> None:
        class Item:
            def __init__(self, name: str, value: str) -> None:
                self.name = name
                self.value = value

        result = validate_env_vars_input_list(
            [Item("FOO", "1"), Item("BAR", "2")],
            scope="deployment",
        )
        assert result == {"FOO": "1", "BAR": "2"}

    def test_duplicate_name_rejected_before_dict_built(self) -> None:
        with pytest.raises(DuplicateEnvVarNameError) as exc:
            validate_env_vars_input_list(
                [("FOO", "1"), ("BAR", "2"), ("FOO", "3")],
                scope="deployment",
            )
        assert exc.value.error_metadata == {
            "name": "FOO",
            "scope": "deployment",
        }

    def test_input_list_validates_dict_rules(self) -> None:
        with pytest.raises(InvalidEnvVarNameError):
            validate_env_vars_input_list([("1BAD", "v")], scope="deployment")
