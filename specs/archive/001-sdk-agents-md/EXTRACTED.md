# Extraction Record

**Extracted on**: 2026-05-01
**Extracted by**: speckit.extract

## ADRs Created

None. This was a documentation-only feature; no new architectural decisions
were made. Research entries R1–R7 are meta-decisions about how to author
the new doc, not about system architecture.

## Knowledge Updated

None. The deliverable (`python_sdk/AGENTS.md`) is the authoritative
documentation; duplicating its content under `dev/knowledge/python_sdk/`
would invite drift from the colocated source of truth.

## Guidelines Updated

None. Prescriptive SDK conventions ("never edit `_generated/`", "update
both `.graphql` AND Python wiring", etc.) are captured in
`python_sdk/AGENTS.md`'s **Always Do / Ask First / Never Do** section,
mirroring the per-area pattern established by `backend/AGENTS.md` and
`frontend/AGENTS.md`.

## Archive

Spec directory moved to `specs/archive/001-sdk-agents-md/` as a historical
record of how the SDK doc was produced. The deliverable lives at
`python_sdk/AGENTS.md` and is referenced from the repo-root `AGENTS.md`.
