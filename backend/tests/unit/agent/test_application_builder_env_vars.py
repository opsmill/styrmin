"""Unit tests for env vars wiring into the application builder (T028).

Asserts that ``ApplicationHelmReleaseBuilder.build_env_vars_post_rendering_patches``
is invoked from ``build()`` and that emitted patches reach ``target_patches``
in the rendered ``HelmRelease``. Mirrors
``test_application_builder_scheduling.py``.
"""

from __future__ import annotations

import inspect

from styrmin_backend.agent.service.kubernetes.resources.builders import application


class TestEnvVarsBuilderWiring:
    def test_build_invokes_env_vars_helper(self) -> None:
        build_source = inspect.getsource(
            application.ApplicationHelmReleaseBuilder.build
        )
        assert "build_env_vars_post_rendering_patches" in build_source, (
            "env vars helper not wired into build()"
        )

    def test_env_vars_patches_come_after_scheduling_in_build(self) -> None:
        """Env var patches must appear AFTER scheduling patches in the
        ``target_patches`` list. Order matters because Kustomize applies
        patches in order; env vars riding the same strategic-merge path as
        any future scheduling-touching patch should win on container env
        keys regardless. Today scheduling does not touch env entries, so
        the order is policy more than mechanism.
        """
        build_source = inspect.getsource(
            application.ApplicationHelmReleaseBuilder.build
        )
        scheduling_idx = build_source.find("build_scheduling_post_rendering_patches")
        env_vars_idx = build_source.find("build_env_vars_post_rendering_patches")
        assert scheduling_idx != -1
        assert env_vars_idx != -1
        assert env_vars_idx > scheduling_idx, (
            "env vars patches must be appended after scheduling patches"
        )
