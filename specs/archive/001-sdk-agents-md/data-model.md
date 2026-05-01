# Data Model: Python SDK AGENTS.md

**Feature**: 001-sdk-agents-md
**Date**: 2026-05-01

This is a documentation feature; "data model" describes the documentation
**assets** produced or modified, not runtime data structures.

## Assets

### Asset: `python_sdk/AGENTS.md` (NEW)

**Purpose**: Per-area orientation document for AI agents and human
contributors working on the Python SDK.

**Required sections** (see `contracts/agents-md-outline.md` for the
authoritative outline):

1. Title + one-sentence description
2. Tech Stack
3. File Structure (mapping of top-level SDK modules to roles)
4. Commands
5. GraphQL Workflow — adding/changing an operation (with the explicit
   "regen is not enough" callout)
6. Worked example (real snippet from `resources/clusters.py`)
7. Always Do / Ask First / Never Do

**Validation**:

- Every requirement FR-001 through FR-005, FR-008, FR-009 from `spec.md`
  resolves to content in this file.
- All file/module references are real and verifiable by `ls`/`grep`.
- Markdown lints clean against `dev/guidelines/markdown.md`.

**Lifecycle**: Created in this feature. Maintained alongside the SDK; if a
top-level SDK module is added/renamed/removed, this doc's "File Structure"
section must be updated in the same change.

### Asset: `AGENTS.md` (MODIFIED)

**Purpose**: Repo-wide orientation document. Modified to surface the new
SDK doc.

**Edits**:

- **File Structure** section: insert a `python_sdk/` line referencing
  `python_sdk/AGENTS.md`.
- **Component Maps** section: insert a "Python SDK" entry referencing
  `python_sdk/AGENTS.md`.

**Validation**:

- Both changes resolve FR-006 and FR-007.
- Existing entries (backend, frontend, dev, drivers) remain unchanged.
- Insertion order respects the file's existing ordering convention
  (alphabetical-ish: backend, frontend, python_sdk, dev — matching the
  monorepo's logical grouping of producer/consumer code).

## Relationships

```text
CLAUDE.md
  └─ @AGENTS.md (root) ──┬─ links to ──▶ backend/AGENTS.md
                         ├─ links to ──▶ frontend/AGENTS.md
                         └─ links to ──▶ python_sdk/AGENTS.md  ← NEW
```

`CLAUDE.md` already wildcards in `AGENTS.md` via `@AGENTS.md`, so per-area
docs are reachable through the existing chain. No `CLAUDE.md` change is
required.

## Out of Scope

- No changes to `backend/AGENTS.md`, `frontend/AGENTS.md`, or `CLAUDE.md`.
- No changes to `dev/` documentation; if knowledge or ADRs are extracted
  later, that happens in `/speckit.extract` (Phase 6) and is tracked there.
- No changes to SDK source code, tests, or generated files.
