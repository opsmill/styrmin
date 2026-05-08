"""Unit tests for env-vars exposure through ``ApplicationBuilder.render_value_template``.

Phase 1 placeholder — this file exists so pytest collection picks it up.
T004 (Phase 2) will replace ``test_placeholder`` with the real verification:
feed a synthetic ``GlobalContext`` (env vars set at deployment + per-component
scope) through ``ApplicationBuilder.render_value_template`` with a probe Jinja
template that reads ``instance.config.env_vars`` and
``components[<name>].env_vars.config``, asserting the rendered output reflects
the expected values. See ``specs/010-driver-env-var-consumption/tasks.md``.
"""

from __future__ import annotations


def test_placeholder() -> None:
    """Placeholder so the file collects under pytest. Replaced in T004."""
    assert True
