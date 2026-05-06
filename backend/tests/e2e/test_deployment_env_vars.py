"""Placeholder E2E coverage for deployment environment variables (008).

Real scenarios land in T030 / T037 / T046. This stub keeps the file wired into
pytest collection so the orchestrator can confirm the suite exists.
"""

import pytest


@pytest.mark.api_only(reason="Placeholder; real scenarios land in T030/T037/T046.")
@pytest.mark.ci
async def test_placeholder() -> None:
    """Placeholder kept until US1 lands."""
    assert True
