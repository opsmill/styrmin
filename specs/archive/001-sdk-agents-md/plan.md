# Implementation Plan: Python SDK AGENTS.md

**Branch**: `001-sdk-agents-md` | **Date**: 2026-05-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-sdk-agents-md/spec.md`

## Summary

Add a new `python_sdk/AGENTS.md` documenting the SDK's architecture (transport, client, resources, generated models, `.graphql` operation files loaded via `load_query()`), the manual workflow for adding a new SDK operation (including the explicit warning that GraphQL regen does NOT auto-wire Python code), and an "Always Do / Ask First / Never Do" boundaries section consistent with the top-level `AGENTS.md`. Update the top-level `AGENTS.md` to reference the new SDK doc in both **File Structure** and **Component Maps** sections. This is a documentation-only change; no runtime, schema, or build behavior is altered.

## Technical Context

**Language/Version**: N/A (Markdown documentation)
**Primary Dependencies**: None
**Storage**: Files in repository (`python_sdk/AGENTS.md`, `AGENTS.md`)
**Testing**: Manual review against spec acceptance criteria; no automated tests
**Target Platform**: Repository — files are consumed by AI coding agents (via `@AGENTS.md` include in `CLAUDE.md`) and human contributors
**Project Type**: Documentation update inside an existing monorepo
**Performance Goals**: N/A
**Constraints**:
- Markdown style follows `dev/guidelines/markdown.md`
- Must remain consistent with existing `backend/AGENTS.md` and `frontend/AGENTS.md` tone and structure
- Must not duplicate repo-wide GraphQL conventions already in top-level `AGENTS.md`; references them instead
**Scale/Scope**: One new file (~150–250 lines), one existing file edited in two sections.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applies? | Status | Notes |
|-----------|----------|--------|-------|
| I. Declarative State Reconciliation | No | Pass | Docs-only; no runtime behavior. |
| II. Driver-Based Deployment | No | Pass | Not driver-related. |
| III. Layered Architecture | No | Pass | No code changes. |
| IV. Type Safety and Typed Errors | No | Pass | No code changes. |
| V. Test-First Development | Yes (with documented exemption) | Pass | This is a docs-only feature. The deliverable IS documentation — there is no user-visible behavior change to exercise via E2E. The §V exemption for "doc updates" applies; verification is by review against spec acceptance criteria. The reviewer's approval authorizes skipping E2E. |
| VI. Format and Lint Before Commit | Yes | Pass | `uv run invoke format lint` runs as usual; markdown is unaffected by ruff but the command is no-op-safe. |

**Governance gates** (Database, GraphQL schema, new dependencies, CI/CD, auth): None triggered.

**Result**: All gates pass. No complexity entries required.

## Project Structure

### Documentation (this feature)

```text
specs/001-sdk-agents-md/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (doc-asset model only)
├── quickstart.md        # Phase 1 output (review steps)
├── contracts/
│   └── agents-md-outline.md   # Required structure of python_sdk/AGENTS.md
├── checklists/
│   └── requirements.md  # From Phase 1 (specify)
├── spec.md              # From Phase 1 (specify)
└── tasks.md             # Created by /speckit.tasks
```

### Source Code (repository root)

```text
.
├── AGENTS.md                  # MODIFIED: add references in File Structure + Component Maps
├── backend/AGENTS.md          # unchanged (precedent)
├── frontend/AGENTS.md         # unchanged (precedent)
└── python_sdk/
    ├── AGENTS.md              # NEW: SDK orientation doc
    └── src/styrmin_sdk/       # described by the new doc, not edited
        ├── client.py
        ├── _transport.py
        ├── _queries.py        # load_query() utility
        ├── exceptions.py
        ├── resources/
        │   ├── _base.py
        │   ├── clusters.py
        │   ├── deployments.py
        │   └── ...            # one module per resource
        └── graphql/
            ├── *.graphql      # one operation per file
            └── _generated/    # do-not-edit Pydantic models
```

**Structure Decision**: Documentation-only edit. Two file system locations: a new file at `python_sdk/AGENTS.md` and an in-place edit of the existing `AGENTS.md` at the repo root. No source code changes.

## Complexity Tracking

> No constitutional violations to justify. Section intentionally empty.
