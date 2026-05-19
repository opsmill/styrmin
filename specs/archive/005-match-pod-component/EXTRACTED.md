# Extraction Record

**Extracted on**: 2026-05-01
**Extracted by**: speckit.extract (archive-only)

## ADRs Created

None — durable content from `research.md` §2 was already captured during
implementation as
[ADR-007](../../dev/adr/adr-007-pod-status-records-observed-state-not-declared-state.md).

The remaining `research.md` entries (§1, §3, §4, §5) were judged not durable
enough to warrant their own ADR or guideline:

- §1 (read labels at `_extract_pod_data`): local implementation detail.
- §3 (normalize blank/whitespace to `None` at the agent boundary): single
  current consumer; codified in code rather than as a guideline.
- §4 (no migration backfill for ephemeral observed-state columns): one
  instance; revisit if a second observed-state table makes the same call.
- §5 (SDK query updates): routine codegen step, already covered by
  AGENTS.md "Always Do" rules.

## Knowledge Updated

None — `PodStatus.component_name` was already documented in
[`dev/knowledge/backend/data-models.md`](../../dev/knowledge/backend/data-models.md)
during implementation, with a cross-reference to ADR-007.

## Guidelines Updated

None.

## Archive

Spec directory moved to `specs/archive/005-match-pod-component/` as a
historical record.
