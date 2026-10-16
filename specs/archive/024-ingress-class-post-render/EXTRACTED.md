# Extraction Record

**Extracted on**: 2026-10-16
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-071](../../../dev/adr/0071-ingress-class-set-by-post-render.md) was written during
implementation and records research D-001 to D-004.

## ADRs Updated

- dev/adr/0071-ingress-class-set-by-post-render.md (source path moved to the archive)

## Knowledge Updated

- dev/knowledge/backend/e2e-testing.md (E2E fixture drivers `late-container` and
  `failing-actions` keep the Ingress class line on purpose; the test that checks their Ingress)
- dev/knowledge/backend/data-models.md (`DedicatedIngressConfig`: `implementation` accepts any
  string, and the deployed controller is always Traefik)

`CONTEXT.md`, `dev/knowledge/backend/data-models.md` and the `docs/` pages were already updated
during implementation (commits `98151399`, `2ae71d0d`, `3e4dd60e`, `59490163`, `ee59d940`).

## Guidelines Updated

- dev/guidelines/backend/python.md (Rendering Kubernetes manifests: remove a field that the chart
  may not render with a strategic merge `null`)
- dev/guidelines/backend/python.md (Testing: a change to a post-render patch ships an integration
  test that runs `kubectl kustomize`, after `helm template` where the chart matters)

## Not Extracted

The implementation report deferred these review findings. They are follow-up work, not
knowledge:

- move the `helm template` and `kubectl kustomize` helpers that two integration tests copy into
  `backend/tests/helpers/`;
- give strategic merge patches a base class without `_operation` and `_path`;
- add a test that the example drivers keep no class line and keep their `spec.version`.

## Renumbering

The rebase onto `develop` on 2026-10-16 found ADR-070 and spec number 023 already used by
`specs/archive/023-per-component-replicas/`. This spec became 024 and its ADR became ADR-071. The
references in this directory were updated; research D-007 still calls the ADR "the next free
number after ADR-069", which was true when it was written.

## Archive

Spec directory moved to `specs/archive/024-ingress-class-post-render/` as a historical record.
