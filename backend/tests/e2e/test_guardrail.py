"""Tests for the E2E-suite collection guardrail.

Runs as a normal pytest, not part of CI. Uses pytester to drive a fresh
pytest collection inside a temp directory and assert the guardrail rejects
tests that lack the required shard_* marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

# backend/ directory — needed so pytester's inner session can resolve
# `from tests.e2e.conftest import enforce_shard_markers`.
_BACKEND_DIR = Path(__file__).parents[2]


_INI = """
[pytest]
markers =
    ci: foo
    shard_general: foo
    shard_env: foo
    shard_compute: foo
    shard_backup: foo
    shard_configuration: foo
"""


def test_collection_fails_when_ci_test_lacks_shard_marker(
    pytester: pytest.Pytester,
) -> None:
    pytester.syspathinsert(_BACKEND_DIR)
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import enforce_shard_markers  # noqa: F401


def pytest_collection_modifyitems(config, items):
    enforce_shard_markers(config, items)
""",
        test_bad="""
import pytest


@pytest.mark.ci
def test_missing_shard():
    pass
""",
    )
    pytester.makeini(_INI)
    result = pytester.runpytest_inprocess("--collect-only")
    assert result.ret != 0
    result.stdout.fnmatch_lines(
        ["*missing required @pytest.mark.shard_*test_missing_shard*"]
    )


def test_collection_passes_when_ci_test_has_shard_marker(
    pytester: pytest.Pytester,
) -> None:
    pytester.syspathinsert(_BACKEND_DIR)
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import enforce_shard_markers  # noqa: F401


def pytest_collection_modifyitems(config, items):
    enforce_shard_markers(config, items)
""",
        test_good="""
import pytest


@pytest.mark.ci
@pytest.mark.shard_general
def test_has_shard():
    pass
""",
    )
    pytester.makeini(_INI)
    result = pytester.runpytest_inprocess("--collect-only")
    assert result.ret == 0


def test_collection_rejects_multiple_shard_markers(pytester: pytest.Pytester) -> None:
    pytester.syspathinsert(_BACKEND_DIR)
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import enforce_shard_markers  # noqa: F401


def pytest_collection_modifyitems(config, items):
    enforce_shard_markers(config, items)
""",
        test_double="""
import pytest


@pytest.mark.ci
@pytest.mark.shard_general
@pytest.mark.shard_backup
def test_double_marked():
    pass
""",
    )
    pytester.makeini(_INI)
    result = pytester.runpytest_inprocess("--collect-only")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*has multiple shard markers*test_double_marked*"])
