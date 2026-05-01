# Feature Specification: Python SDK AGENTS.md

**Feature Branch**: `001-sdk-agents-md`
**Created**: 2026-05-01
**Status**: Draft
**Input**: User description: "Add `python_sdk/AGENTS.md` documenting the SDK's architecture, the manual Python wiring required when adding/changing GraphQL operations, and standard Always Do/Ask First/Never Do boundaries; update top-level `AGENTS.md` to reference it. Tracks GitHub issue opsmill/styrmin#150."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent or contributor lands in `python_sdk/` and learns how it fits together (Priority: P1)

An agent or human contributor opens the repo and is asked to make a change in the Python SDK (`python_sdk/`). Today, the top-level `AGENTS.md` documents the backend and frontend conventions but does not describe the SDK. The reader has to reverse-engineer the SDK's structure and manual GraphQL wiring conventions from source. With this feature in place, the reader follows the `File Structure` link from the top-level `AGENTS.md`, opens `python_sdk/AGENTS.md`, and gets a concise map of the SDK: how the transport, client, resources, generated models, and `.graphql` files relate.

**Why this priority**: This is the primary value of the feature. Without this orientation document, agents repeatedly produce broken or incomplete SDK changes.

**Independent Test**: Open `python_sdk/AGENTS.md` cold (no other context) and answer "what does each top-level Python module under `python_sdk/src/styrmin_sdk/` do, and where do GraphQL operations live?". The document alone must be sufficient to answer.

**Acceptance Scenarios**:

1. **Given** a contributor reading only `AGENTS.md` files, **When** they want to understand SDK layout, **Then** `python_sdk/AGENTS.md` describes the role of `client.py`, `_transport.py`, `_queries.py`, `resources/`, `graphql/` (operation files), and `graphql/_generated/` (do-not-edit Pydantic models).
2. **Given** a contributor reading the top-level `AGENTS.md`, **When** they look at the **File Structure** and **Component Maps** sections, **Then** both reference `python_sdk/AGENTS.md` alongside `backend/AGENTS.md` and `frontend/AGENTS.md`.

---

### User Story 2 - Agent adds a new GraphQL operation to the SDK without missing the manual Python wiring step (Priority: P1)

An agent is asked to expose a new operation through the SDK (e.g., `get_environment_services`). Today's failure mode: the agent adds a `.graphql` file under `python_sdk/src/styrmin_sdk/graphql/`, runs `uv run invoke generate` to regenerate Pydantic types, and then reports the work as done — but the SDK's Python surface still does not expose the operation, because `client.py`, the relevant `resources/` module, and any related callsites were not updated. With this feature in place, `python_sdk/AGENTS.md` explicitly documents that the GraphQL regen does not auto-wire Python code, and provides the full step-by-step workflow.

**Why this priority**: This is the highest-cost recurring failure mode the issue calls out. Equal priority with Story 1 because both are necessary for the SDK doc to be useful.

**Independent Test**: Show a contributor a hypothetical task ("expose `getDeploymentTimeline` through `client.deployments.get_timeline()`") and ask them to follow `python_sdk/AGENTS.md` step-by-step. The document alone must lead them to (a) create the `.graphql` file, (b) regenerate types, (c) validate, (d) add or update the resource method, (e) wire it into the client if a new resource module is needed, and (f) test.

**Acceptance Scenarios**:

1. **Given** the SDK doc, **When** a reader scans for "adding a new operation", **Then** the doc states explicitly that adding the `.graphql` file and regenerating types is **not enough** — Python code in `resources/` (and possibly `client.py`) must be updated by hand.
2. **Given** the SDK doc, **When** a reader follows the step-by-step workflow, **Then** they encounter the regen commands `uv run styrmin export graphql-schema schema.graphql`, `uv run invoke generate`, and `uv run invoke validate-graphql` in the correct order.
3. **Given** the SDK doc, **When** a reader looks for a worked example, **Then** the doc provides at least one minimal example of an existing resource method (e.g., a small `ClusterResource.get` style snippet) showing how `load_query()` and the generated Pydantic types fit together.

---

### User Story 3 - Agent knows what is safe vs. requires confirmation in the SDK (Priority: P2)

An agent making changes to the SDK has clear boundaries about what is routine, what requires asking first, and what is forbidden — mirroring the structure of the top-level `AGENTS.md`. This prevents the agent from, for example, hand-editing files under `graphql/_generated/`, or silently adding a new HTTP dependency to the transport.

**Why this priority**: P2 because boundary documentation is valuable but not the primary failure mode; Stories 1 and 2 carry most of the user value.

**Independent Test**: A reader can answer "is editing `graphql/_generated/get_cluster.py` allowed?" and "should I introduce a new transport dependency without asking?" purely from the SDK doc.

**Acceptance Scenarios**:

1. **Given** the SDK doc, **When** a reader scrolls to its boundaries section, **Then** an "Always Do / Ask First / Never Do" structure is present, stylistically consistent with the top-level `AGENTS.md`.
2. **Given** the SDK doc, **When** a reader looks at "Never Do", **Then** "edit files under `graphql/_generated/`" is explicitly listed.
3. **Given** the SDK doc, **When** a reader looks at "Ask First", **Then** items at minimum include changes to the transport layer, new third-party dependencies, and changes that break the public client API surface.

---

### Edge Cases

- **Doc rot from architectural change**: If the SDK's structure changes after merge (e.g., `resources/` is reorganized), the doc must still describe the conventions accurately. Mitigation: keep the doc focused on conventions ("operations live in `.graphql` files, loaded via `load_query()`") rather than enumerating every current resource module.
- **Conflicting guidance with top-level `AGENTS.md`**: The top-level already lists the regen commands. The SDK doc must reference (not duplicate) those commands where appropriate, and avoid drifting out of sync.
- **Reader skips top-level**: An agent may open `python_sdk/AGENTS.md` without first reading the root `AGENTS.md`. The SDK doc must still be self-sufficient enough for an SDK change, while still pointing back to root for project-wide rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A new file `python_sdk/AGENTS.md` MUST exist at the SDK package root.
- **FR-002**: `python_sdk/AGENTS.md` MUST document the SDK's high-level architecture, naming and describing each of: the transport layer, the client, the resource modules, the generated Pydantic models, and the `.graphql` operation files (loaded via `load_query()`).
- **FR-003**: `python_sdk/AGENTS.md` MUST explicitly state that adding or changing a GraphQL operation requires BOTH (a) updating the `.graphql` file and regenerating types AND (b) updating Python code (resource methods, and `client.py` if a new resource module is added) — and that neither step happens automatically.
- **FR-004**: `python_sdk/AGENTS.md` MUST document the full step-by-step workflow for adding a new SDK operation, including the regen commands `uv run styrmin export graphql-schema schema.graphql`, `uv run invoke generate`, and `uv run invoke validate-graphql`, in the order they should be run.
- **FR-005**: `python_sdk/AGENTS.md` MUST contain an "Always Do / Ask First / Never Do" boundaries section structurally analogous to the one in the top-level `AGENTS.md`, with SDK-specific entries (including, at minimum: never edit files in `graphql/_generated/`; always run `validate-graphql` after touching `.graphql` files; ask before changing transport, public client API surface, or adding new third-party dependencies).
- **FR-006**: The top-level `AGENTS.md` MUST reference `python_sdk/AGENTS.md` in the **File Structure** section, alongside the existing `backend/` and `frontend/` entries.
- **FR-007**: The top-level `AGENTS.md` MUST reference `python_sdk/AGENTS.md` in the **Component Maps** section, alongside the existing backend, frontend, and drivers entries.
- **FR-008**: `python_sdk/AGENTS.md` MUST reference (not redefine) the project-wide GraphQL operation conventions already documented in the top-level `AGENTS.md` (one operation per `.graphql` file, snake_case file naming derived from operation name, operations must have a name).
- **FR-009**: `python_sdk/AGENTS.md` MUST include at least one minimal worked example showing how a resource method calls `load_query()` and validates a generated Pydantic model.

### Key Entities

- **`python_sdk/AGENTS.md`**: New documentation file. Co-located with the SDK package. Loaded into agent context when work touches `python_sdk/`.
- **Top-level `AGENTS.md`**: Existing documentation file. Modified to add references to the new SDK doc in two sections.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A contributor or agent reading only `python_sdk/AGENTS.md` can describe, without consulting source, what each of the following contains: `client.py`, `_transport.py`, `_queries.py`, `resources/`, `graphql/`, `graphql/_generated/`.
- **SC-002**: A contributor or agent following the SDK doc end-to-end produces a working new operation (`.graphql` file present, types regenerated, resource method wired, query validated) in a single iteration without needing to be told that the Python wiring step exists.
- **SC-003**: From the top-level `AGENTS.md`, a reader can navigate to `python_sdk/AGENTS.md` from both the **File Structure** section and the **Component Maps** section without external search.
- **SC-004**: All three per-area docs (`backend/AGENTS.md`, `frontend/AGENTS.md`, `python_sdk/AGENTS.md`) share the same boundary structure ("Always Do / Ask First / Never Do") so that agents can apply consistent decision-making across areas.

## Assumptions

- The top-level `AGENTS.md` already documents repo-wide GraphQL conventions (one operation per file, snake_case naming, `load_query()` utility, regen commands), so `python_sdk/AGENTS.md` references those rules rather than re-stating them in full.
- Generated files under `python_sdk/src/styrmin_sdk/graphql/_generated/` are considered authoritative output of `uv run invoke generate` and must never be hand-edited; this is conventionally enforced rather than mechanically.
- The intended audience for `python_sdk/AGENTS.md` is both AI agents and human contributors — the same audience as `backend/AGENTS.md` and `frontend/AGENTS.md`.
- This feature is documentation-only: it does not change the SDK's runtime behavior, public API, or generated artifacts.
- E2E test coverage is not applicable; documentation correctness is verified by review (Constitution §V exemption for docs-only changes — the documentation IS the deliverable, not a behavior change to be exercised).
