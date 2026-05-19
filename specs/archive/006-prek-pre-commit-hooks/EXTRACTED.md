# Extraction Record

**Extracted on**: 2026-05-17
**Extracted by**: speckit.extract

## ADRs Created

None — all decisions already captured by [`adr-007-pre-commit-hooks-via-prek.md`](../../dev/adr/adr-007-pre-commit-hooks-via-prek.md), including:

- prek as the sole supported runner (the dual-runner reversal narrative under "Why prek-only")
- Hook-stage split (`pre-commit` vs `pre-push`) for sub-10-second per-commit latency
- The parity-validation period reversal (per-tool jobs removed in the same PR)

## Knowledge Updated

None — operational details (hook list, version pinning, generated-file exclusions, invoke wrapper, bypass policy) are documented in [`dev/guides/pre-commit-hooks.md`](../../dev/guides/pre-commit-hooks.md) and `AGENTS.md` § Bypassing the pre-commit hooks.

## Guidelines Updated

None.

## Archive

Spec directory moved to `specs/archive/006-prek-pre-commit-hooks/` as a historical record.
