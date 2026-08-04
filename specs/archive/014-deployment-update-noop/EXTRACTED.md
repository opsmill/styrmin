# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- `dev/adr/0054-backend-authoritative-noop-detection.md` (from R1 – R9)

## Knowledge Updated

- `dev/knowledge/backend/api.md` (Mutations — annotated the `updateDeployment` and
  `updateDeploymentVersion` rows, and added a "`null` Task means 'no work needed', not
  'error'" subsection). `reconciliation.md` and `services.md` already documented the
  guard; `api.md` — the page a client author reads — did not.

## Guidelines Updated

None.

## Two consequences worth flagging to future readers

- **`null` is now overloaded** on `updateDeployment` / `updateDeploymentVersion`: it
  means "no work needed", where it previously implied only an error path. Any client
  treating a null task as failure is wrong.
- **Resubmitting the same config will not retry a `FAILED` deployment.** `Comparator`
  excludes `status` from the diff, so an identical candidate is a no-op. This falls out of
  existing comparison semantics (R3) rather than any special-casing, and it means recovery
  needs an explicit redeploy path.

## Follow-ups left open

- Exposing `refresh_deployment` as a user-facing redeploy/refresh (the recovery path) —
  separate feature.
- A field-level "what changed" report — additive follow-up; v1 clients learn only
  *whether* anything changed.
- Collapsing the config-update + version-upgrade double reconcile when both change —
  unchanged from spec 009.

## Historical note

This feature **reverted** the client-side change detection shipped as stopgap `6f8713a`
(empty-input skip + client-side version compare in the SDK). The `unchanged` action value
survives, but it is now driven by the backend's null signal rather than a client diff.

## Archive

Spec directory moved to `specs/archive/014-deployment-update-noop/` as a historical record.
