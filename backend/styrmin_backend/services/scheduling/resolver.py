"""Thin API-facing wrapper for scheduling resolution.

Delegates to :mod:`styrmin_backend.context.resolvers` so that API consumers
can surface resolved scheduling configuration (with provenance) without
reaching into the context package.
"""
