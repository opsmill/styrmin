# Extraction Record

**Extracted on**: 2026-10-03
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- None. [ADR-057](../../../dev/adr/0057-post-render-component-overrides.md) was written during
  implementation and already records D-001 – D-011; its `Source` now points at this archive.

## Knowledge Updated

- dev/knowledge/agent/operator.md (Managed Resources → Apply semantics)
- dev/knowledge/backend/api.md (Deployment → Component container read fields)
- dev/knowledge/backend/data-models.md (ComponentConfig)
- dev/knowledge/backend/e2e-testing.md (`api_only` audit discipline — `set_component_env_vars`)

## Guidelines Updated

- dev/guidelines/backend/python.md (Error Handling → Retiring a driver-facing template surface)
- dev/guidelines/backend/python.md (Error Handling → Validate config writes by delta when a driver change can strand stored values)
- dev/guidelines/backend/python.md (Rendering Kubernetes manifests → Per-component pod overrides go through post-render into the component container)
- dev/guidelines/backend/python.md (Rendering Kubernetes manifests → Custom-resource updates: replace the spec keys you write, merge the rest)

## Links Repointed

- dev/adr/0057-post-render-component-overrides.md (`Source`)
- dev/knowledge/backend/deployment-env-vars.md
- dev/guides/driver-env-var-consumption.md
- backend/tests/unit/services/driver/test_example_drivers_container.py (comment)

## Archive

Spec directory moved to `specs/archive/017-post-render-env-vars/` as a historical record.
