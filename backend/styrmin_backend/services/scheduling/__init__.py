"""Scheduling service package.

Hosts resolution, validation, and post-renderer patch building for the
hierarchical pod scheduling & resource configuration feature.

The canonical JSON Schema for the feature's configuration surface lives at
``specs/001-pod-scheduling-config/contracts/scheduling-config.schema.json``;
the Pydantic models in :mod:`styrmin_backend.context.models.config` are the
authoritative runtime representation and this package re-exports them for
API-side consumers.
"""
