# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- `dev/adr/0051-styrminctl-credential-resolution-and-token-store.md` (from R2, R4, R6, R8, R10, R11)

## Knowledge Updated

- `dev/knowledge/cli/overview.md` (**new file** — no `dev/knowledge/cli/` existed;
  documents the invocation pipeline, the credential chokepoint, the token store, and
  the error boundary; shared with spec 015-styrminctl-telemetry)

## Guidelines Updated

- `dev/guidelines/cyclopts.md` (Error Handling — "One line, never a traceback" and
  "CLI-local errors are not service-layer errors")
- `dev/guidelines/cyclopts.md` (**new section** "CLI-local persisted state" — XDG path,
  `0600`/`0700` reasserted, atomic temp + `os.rename()`, `schema_version`; shared with
  spec 015-styrminctl-telemetry)
- `dev/guidelines/cyclopts.md` (Key Files — added the entry point, errors module,
  client chokepoint, and token store)

## Also updated

- `cli/README.md` — repointed the credential-precedence link and linked ADR-051

## Correction recorded during extraction

The research (R6) and the resolver's inline comments number the precedence rungs
`env / file / auto-login`. The **shipped** evaluation order in
`auth/resolver.py::resolve` places auto-login *above* the disk token. ADR-051 and the
knowledge page document the effective order (env → auto-login → file → none) and note
that the rung numbering is nominal.

## Not extracted

- R1 (no `expiresAt` on `LoginResult` — resolved as no change), R3 (`CONTEXT.md`
  vocabulary deferred; the follow-up for `Session` / `Session token` / `Token store`
  glossary entries remains **open**), R5 (`getpass` choice), R9 (code survey),
  R12 (test inventory).

## Archive

Spec directory moved to `specs/archive/011-styrminctl-auth/` as a historical record.
