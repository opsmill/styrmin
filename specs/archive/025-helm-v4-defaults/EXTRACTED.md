# Extraction Record

**Extracted on**: 2026-10-16
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-072](../../../dev/adr/0072-helm-v4-defaults-releases-keep-apply-method.md) was written during implementation and records R-001 to R-008.

## ADRs Updated

- dev/adr/0072-helm-v4-defaults-releases-keep-apply-method.md (Source links point to the archive; §5 states that the per-component label patch also uses `MetadataLabelsMergePatch` since commit c7a151ac)

## Knowledge Updated

- dev/knowledge/agent/operator.md (FluxCD controllers, Readiness timeout, Rollback reported Ready, Steps of a rollout: links point to the archive)
- dev/knowledge/agent/overview.md (Post-render patches and the Helm hooks they reach; from data-model.md, checked against the code)
- dev/knowledge/backend/backup-restore.md (Release records written by Helm v4; from R-006)
- dev/knowledge/backend/e2e-testing.md (Test drivers: the E2E vcluster has one node; from R-009)

## Guidelines Updated

- dev/guidelines/backend/python.md (Rendering Kubernetes manifests: "Add keys to a map that the resource may not have with a strategic merge", from R-008)
- dev/guidelines/backend/python.md (Rendering Kubernetes manifests: "Post-render patches also reach Helm hooks", from R-007)
- dev/guidelines/backend/python.md (Testing: test-only chart behaviour behind an off-by-default value and a test driver, from plan D-002)

## Not Extracted

- research.md R-008 names a limitation of the backup `TemplateAnnotationPatch` that the code does not have; ADR-072 records the correction.
- data-model.md's Helm hook table predates the replica patch of ADR-070 and leaves out the backup and Ingress patches; the table in dev/knowledge/agent/overview.md replaces it.

## Archive

Spec directory moved to `specs/archive/025-helm-v4-defaults/` as a historical record.
