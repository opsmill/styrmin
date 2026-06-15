# ADR-014: Schema-Walking Propagation Tests for Strawberry Input Completeness

**Status**: Accepted
**Date**: 2026-05-10
**Source**: specs/archive/011-env-config-input-hardening/ (research §1, spec.md US1)

## Context

Typed Strawberry inputs that mirror Pydantic config models (e.g. `UpdateEnvironmentInput` ↔ `EnvironmentConfig`) implement full-replacement semantics: missing input fields silently round-trip to `None` on save. Spec 011 caught a real data-loss bug — `ingress_class` and `db_size` lived on `BaseConfigSection` but were never added to `UpdateEnvironmentInput`, so any environment with them set lost them on the next env-vars save. Per-field round-trip tests catch regressions on known fields but are structurally blind to **drift** when a new Pydantic field is added without its input mirror.

## Decision

Every Strawberry input that mirrors a Pydantic config model MUST have a schema-walking completeness test that introspects `<PydanticModel>.model_fields` and `<StrawberryInput>.__strawberry_definition__.fields` and asserts every Pydantic field has a same-camelCase Strawberry counterpart. The assertion is **one-directional** — Strawberry may carry extra helper fields; every Pydantic field must be reachable through the input.

The exemplar lives at `backend/tests/functional/graphql/test_environment_update_propagation.py`; see [`dev/guides/graphql-propagation-tests.md`](../guides/graphql-propagation-tests.md) for the recipe.

## Consequences

- Adding a field to a mirrored Pydantic model and forgetting the Strawberry input fails CI with a message that names the missing field and the file to edit.
- The schema walk is fail-on-drift; per-field round-trip tests are fail-on-regression. Both stay; neither subsumes the other.
- The walk does **not** assert type compatibility (Pydantic `Literal` → Strawberry enum) — that stays with the per-field tests.
