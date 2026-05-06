"""Resolver stubs for layered deployment environment variables.

Real resolution logic (driver defaults -> environment overrides -> deployment
overrides) lands in a later phase. This stub keeps the module importable.
"""


class _EnvVarsResolverPlaceholder:
    """Sentinel placeholder so the module exposes at least one symbol."""
