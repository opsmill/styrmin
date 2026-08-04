# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## No new ADR

[`dev/adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md`](../../../dev/adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md)
was written during implementation and is comprehensive. It covers R1 (the
`_AuthBoundaryApp` chokepoint), R2/R3 (closed-set `command` via `parse_commands`,
option-*names* only, and the hard constraint that extraction must never trigger Cyclopts
value conversion), R4 (daemon thread + bounded join, `TELEMETRY_BUDGET_MS = 200`),
R7 (type-keyed `error_category`), R8 (the eligibility ladder), and the opt-out stance.
`CONTEXT.md` carries the **Telemetry** glossary entry.

## ADRs Created

None.

## Knowledge Updated

- `dev/knowledge/cli/overview.md` (**new file**, shared with spec 011-styrminctl-auth) —
  the Telemetry section describes the pipeline position (telemetry wraps the auth boundary
  from the *outside*, so a credential failure's `SystemExit(1)` is the classified
  outcome), the closed key set, dispatch, the opt-out ladder, and the state file.

## Guidelines Updated

- `dev/guidelines/cyclopts.md` (**new section** "CLI-local persisted state", shared with
  spec 011-styrminctl-auth) — R6's decision to mirror `TokenStore` exactly is what turned
  that write contract into a house pattern, so it is now written down once: XDG path,
  `0600`/`0700` reasserted on every save, atomic temp + `os.rename()`, integer
  `schema_version`, and when to degrade versus raise on an unwritable directory (telemetry
  falls back to an ephemeral `install_id`; the token store raises).
- `dev/guidelines/cyclopts.md` (Error Handling) — records that telemetry buckets failures
  by existing exception **type** and that new exception classes must not be invented for
  categorisation.

## Not extracted

R5 (`httpx` as a direct dependency of the `cli` package — already transitive via the
SDK), R9 (coarse environment facts), R10 (checksum reproducibility) — all are wire-format
and dependency-posture details recorded authoritatively in
`contracts/telemetry-wire-format.md` and ADR-047.

## Archive

Spec directory moved to `specs/archive/015-styrminctl-telemetry/` as a historical record.
