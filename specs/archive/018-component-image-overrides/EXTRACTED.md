# Extraction Record

**Extracted on**: 2026-10-05
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- None. [ADR-058](../../../dev/adr/0058-image-overrides-and-component-container-guard.md) was
  written during implementation and already records D-001 – D-013; its `Source` now points at this
  archive.

## Knowledge Updated

- dev/knowledge/backend/api.md (Image override fields: entry order, `resolvedReference` with an empty version)
- dev/knowledge/cli/overview.md (Declarative apply: pinned image warning, clearing config)
- dev/knowledge/frontend/deployment-configuration.md (Component env vars follow the component container: read summary and upgrade dialog)

## Guidelines Updated

- dev/guidelines/backend/python.md (Service Layer → Validate before any step that starts a flow run)
- dev/guidelines/backend/python.md (Error Handling → Validate config writes by delta when a driver change can strand stored values)
- dev/guidelines/backend/python.md (Rendering Kubernetes manifests → Per-component pod overrides go through post-render into the component container)
- dev/guidelines/backend/python.md (Testing → shared test-vector files)

## Links Repointed

- dev/adr/0058-image-overrides-and-component-container-guard.md (`Source`)
- CLAUDE.md (Spec Kit active feature plan)
- backend/styrmin_backend/services/image_overrides/__init__.py (docstring)
- backend/styrmin_backend/services/component_container/__init__.py (docstring)
- spec.md (ADR-057 link, one level deeper)

## Archive

Spec directory moved to `specs/archive/018-component-image-overrides/` as a historical record.
