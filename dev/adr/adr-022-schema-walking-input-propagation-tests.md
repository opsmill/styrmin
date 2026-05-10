# ADR-022: Schema-Walking Propagation Tests for Strawberry Input Completeness

**Status**: Accepted
**Date**: 2026-05-10
**Source**: specs/archive/011-env-config-input-hardening/ (research §1, spec.md US1)

## Context

Spec 009 introduced typed Strawberry inputs (e.g. `UpdateEnvironmentInput`) that
mirror Pydantic config models (e.g. `EnvironmentConfig` via
`BaseConfigSection`). These inputs implement **full-replacement semantics**:
the mutation handler converts the typed input into the Pydantic model and
overwrites the persisted config wholesale.

Spec 011 surfaced a real bug: when a Pydantic field exists but its Strawberry
mirror does not, the missing field silently round-trips to `None` on every
save. Concretely, `ingress_class` and `db_size` lived on `BaseConfigSection`
but were never added to `UpdateEnvironmentInput`. Any environment with these
fields set lost them on the next env-vars save through the UI — a data-loss
bug indistinguishable from operator error.

The existing per-field propagation tests (one test per known field) caught
**regressions** on already-known fields but were structurally blind to
**drift**: nothing fails when a new field is added to the Pydantic model and
forgotten on the input.

## Decision

Every Strawberry input that mirrors a Pydantic config model MUST have a
**schema-walking propagation test** alongside the per-field round-trip tests.
The walk introspects both sides at runtime and asserts every Pydantic field
has a Strawberry counterpart of the same camelCase name:

```python
def test_update_environment_input_covers_every_environment_config_field():
    """Schema-walking completeness check.

    Walks `EnvironmentConfig.model_fields` (Pydantic) and asserts that for
    every field, an equivalently-named Strawberry field exists on
    `UpdateEnvironmentInput`. Future schema drift — e.g., adding a field to
    `BaseConfigSection` without updating the input — fails this test with a
    precise message.
    """
    from styrmin_backend.context.models.config import EnvironmentConfig
    from styrmin_backend.api.definitions.environment.inputs import (
        UpdateEnvironmentInput,
    )

    input_field_names = {
        f.python_name
        for f in UpdateEnvironmentInput.__strawberry_definition__.fields
    }
    pydantic_field_names = set(EnvironmentConfig.model_fields.keys())

    missing = pydantic_field_names - input_field_names
    assert not missing, (
        f"UpdateEnvironmentInput is missing {missing} — every "
        f"EnvironmentConfig field MUST have a corresponding input field. "
        f"Add the field to "
        f"backend/styrmin_backend/api/definitions/environment/inputs.py."
    )
```

The test lives next to the existing per-field propagation tests
(`backend/tests/functional/graphql/test_environment_update_propagation.py`)
and runs as part of the propagation suite on every CI run.

The Strawberry side is allowed to have **additional** fields (helper inputs,
explicit overrides) — the assertion is one-directional: every Pydantic field
must be reachable through the input.

## Consequences

- Adding a field to a mirrored Pydantic model and forgetting the Strawberry
  input now fails CI loudly, with a message that names the missing field and
  the file to edit.
- The cost is one ~20-line test per `(Pydantic config, Strawberry input)`
  pair. The tests are cheap, deterministic, and self-documenting; they don't
  spin up a cluster or hit the database.
- The pattern composes with Pydantic v2's `model_fields` introspection and
  Strawberry's `__strawberry_definition__.fields` — no third-party schema
  registry is required.
- The test does **not** assert type compatibility (e.g. that a Pydantic
  `Literal["http", "https"]` corresponds to a `Strawberry` enum). Type
  mismatches are caught by the per-field round-trip tests; the schema walk
  is a structural existence check only.
- Future config models that add fields without input mirrors fail fast
  rather than corrupt data silently. This is the inversion of the per-field
  tests' "fail-on-regression" stance — the schema walk is "fail-on-drift".

## Alternatives Considered

- **Static analysis via a custom `ruff`/`ty` rule**: rejected — too much
  infrastructure for a single-shot check; would need maintenance separate
  from the test suite.
- **CI step that diffs `schema.graphql`**: rejected — the schema regen step
  catches *fields that exist in Strawberry* but doesn't catch fields that
  *should* exist. The check needs to be Pydantic-driven, not schema-driven.
- **Per-field manual propagation test for every future field**: rejected —
  the existing per-field tests stay (they catch type-shape regressions),
  but adding one for every future field puts the maintenance burden on the
  wrong side. The schema walk is fail-on-drift; per-field tests are
  fail-on-regression. Both are needed; neither subsumes the other.
- **Inverse direction (Strawberry → Pydantic)**: deliberately not asserted.
  Strawberry inputs may legitimately carry fields with no Pydantic
  counterpart (e.g. helper or convenience inputs). The asymmetry is
  intentional.
