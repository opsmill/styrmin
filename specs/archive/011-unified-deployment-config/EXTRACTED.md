# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- `dev/adr/0052-client-side-config-diff-impact-and-conflict-detection.md`
  (from R-003, R-004, R-005, R-012 including the shipped Strategy B, and R-013)

## Knowledge Updated

- `dev/knowledge/frontend/deployment-configuration.md` (**new file** — nothing in `dev/`
  described `ConfigEditDrawer`, `config-diff.ts`, or `impact-rules.ts`: file layout, the
  eight sections, draft lifecycle, diff → impact → apply, inheritance state, the
  concurrent-edit path, and the env-var plaintext posture)

## Guidelines Updated

- `dev/guidelines/frontend/forms.md` (**new sections** — "Multi-section drawers: one form
  instance, per-section schemas", "Discard confirmation instead of autosave", and
  "Beware the unset-array normalisation")

## Standing maintenance cost recorded

Adding a deployment-config field now requires touching `frontend/src/lib/config-diff.ts`
and — if the field can disrupt pods — `frontend/src/lib/impact-rules.ts`. Nothing
enforces this; the field otherwise changes with no diff entry and no impact line. Called
out in both the ADR and the knowledge page.

## Follow-ups left open

- **Strategy A** (expose the existing `Deployment.updated_on`, return a typed
  `STALE_DEPLOYMENT_WRITE` error) is deferred, not rejected — the audit in `research.md`
  confirmed the column exists and is simply unexposed. It can land without touching
  dialog code.
- `Deployment.lastUpdateEvent` for the hero summary — v1 derives it client-side.

## Not extracted

- R-001 (TanStack Form choice), R-002 (Base UI Dialog over Vaul), R-006
  (`IntersectionObserver` scrollspy), R-008 (`ParameterField` extraction), R-010
  (`ui_only` E2E marker), R-011 (legacy `SchedulingConfigDialog` removal sequencing) —
  reuse and no-new-dependency calls already covered by existing frontend guidelines and
  AGENTS.md.

## Archive

Spec directory moved to `specs/archive/011-unified-deployment-config/` as a historical record.
