# Feature Specification: Dual-Entrypoint E2E Tests (API and UI)

**Feature Branch**: `001-dual-e2e-entrypoints`
**Created**: 2026-04-22
**Status**: Draft
**Input**: User description: "I want pytest-playwright based E2E tests; I want the current e2e tests to have two 'entrypoints': one through the APIs (this is what we have currently), the other one through the frontend UI (this is what we want to build); test content must be identical, it's just the entrypoint that change; if there's anything missing in the frontend to achieve the tests (and vice versa) you must implement it"

## Clarifications

### Session 2026-04-22

- Q: Which browser(s) must the UI-entrypoint tests run against? → A: Chromium only
- Q: Does the UI entrypoint include pixel-level visual regression assertions, or only behavioral assertions with screenshots as failure diagnostics? → A: Behavior-only; screenshots/traces are diagnostics on failure, not assertions
- Q: How do UI-entrypoint failures gate CI? → A: Blocking — UI failures block PR merges on the same gate as API failures
- Q: What retry policy applies to failing UI-entrypoint tests? → A: One automatic retry; first-attempt diagnostics still recorded
- Q: How are API and UI variants isolated from one another when both run for the same scenario? → A: They run in separate CI jobs against separate backends, never simultaneously against the same backend; no new naming scheme is required

## User Scenarios & Testing *(mandatory)*

### User Story 1 - UI regressions caught by the existing E2E suite (Priority: P1)

Today, the E2E suite only exercises the platform through its programmatic client. A frontend change that breaks a deployment form, a backup dialog, or the timeline view can ship without any E2E signal. In this story, every current E2E scenario runs a second time through the web UI — same pre-conditions, same actions, same assertions — producing a pass/fail signal that specifically reflects whether a real user could still perform the workflow through the product.

**Why this priority**: This is the whole point of the feature. Without this, UI regressions continue to leak past the test suite, which is the gap the user is trying to close. Even a single scenario running through both entrypoints already delivers value: it proves the parity model works and immediately expands coverage.

**Independent Test**: Take one existing API-driven scenario (e.g. "deploy an app and verify it is running"), add its UI-driven sibling, intentionally break a selector/button the UI test relies on, and confirm the UI variant fails while the API variant still passes. That single round-trip demonstrates the new safety net.

**Acceptance Scenarios**:

1. **Given** an existing E2E scenario that passes through the API entrypoint, **When** it is also run through the UI entrypoint against the same healthy backend, **Then** it passes with the same assertion outcomes.
2. **Given** a UI regression that does not affect the programmatic interface, **When** the E2E suite runs, **Then** the UI variant of the affected scenario fails while the API variant still passes, and the failure clearly identifies which entrypoint failed.
3. **Given** a scenario is failing via the UI entrypoint, **When** an engineer opens the test report, **Then** they see a diagnostic artifact (visual capture of the failing state plus a navigable trace of the steps) sufficient to debug without re-running locally.

---

### User Story 2 - Scenario definitions are written once and executed twice (Priority: P1)

Every E2E scenario is defined as a single description of "what happens" — pre-conditions, the sequence of user actions, and the outcome. The two entrypoints (programmatic and UI) are interchangeable drivers that execute that same description. An engineer adding a new scenario writes the description once; both entrypoint runs are produced automatically. An engineer modifying a scenario edits one place.

**Why this priority**: Duplication is the reason dual-entrypoint test suites rot. If the UI and API variants drift, the parity promise is broken and the whole feature loses its value. Building the single-source-of-truth model is inseparable from shipping the UI entrypoint — priority is P1 alongside Story 1.

**Independent Test**: Add a new scenario by writing only its scenario description. Without further changes, observe that it runs via both entrypoints and that the action steps resolve to API calls in one run and to UI interactions in the other.

**Acceptance Scenarios**:

1. **Given** a new E2E scenario needs to be added, **When** an engineer writes its scenario definition once, **Then** it is executed via both entrypoints with no duplicated scenario code.
2. **Given** an existing scenario changes (e.g. an additional assertion), **When** the definition is edited in one place, **Then** both entrypoint runs reflect the change immediately.
3. **Given** the suite is executed, **When** results are reported, **Then** each scenario appears labelled with its entrypoint so API-only and UI-only failures are distinguishable at a glance.

---

### User Story 3 - Close product gaps exposed by parity (Priority: P2)

Some scenarios currently covered by the API suite cannot be fully reproduced through the UI today (for example, setting service-name overrides at deploy time, assigning a backup storage location to an environment, or deleting an environment). Rather than skipping those scenarios on the UI side, the missing product flows are added to the UI so that parity is genuine. The same principle applies in the opposite direction: if any scenario needs an API capability that does not yet exist, the API is extended.

**Why this priority**: Fills the "and vice versa" part of the user's request. It is P2 because the parity infrastructure (Stories 1 and 2) must exist first for these gaps to even be visible as failing tests. Once parity is in place, this story is what makes parity *complete* rather than *partial*.

**Independent Test**: For each scenario the UI cannot fully perform today, verify that after this story the UI flow exists and the scenario's UI variant passes. For each scenario using an API capability that turns out to be missing, verify the API has been extended and both variants pass.

**Acceptance Scenarios**:

1. **Given** an E2E scenario needs an action that has no UI flow today, **When** this feature ships, **Then** the UI flow exists, is reachable from the normal navigation of the product, and the scenario's UI variant passes.
2. **Given** an E2E scenario requires configuration or data the UI does not surface, **When** this feature ships, **Then** that configuration is reachable through the UI (not only through hidden/admin-only affordances).
3. **Given** a scenario is genuinely impossible to express through the UI even after extension (e.g. because it targets an internal-only operation), **When** the suite runs, **Then** that scenario is explicitly and intentionally marked as API-only with a recorded justification, rather than silently skipped.

---

### User Story 4 - Selective execution for fast local iteration (Priority: P3)

Engineers frequently need to run just one side of the suite: a frontend engineer debugging a dialog does not want to wait on the API variants; a backend engineer changing GraphQL does not need the UI runs. The suite supports selecting all tests, only API-entrypoint tests, or only UI-entrypoint tests, and also narrowing to a specific scenario.

**Why this priority**: Quality-of-life. The feature functions without it, but adoption suffers if developers cannot iterate quickly on their side.

**Independent Test**: From a clean checkout, invoke the suite in three modes (all / API-only / UI-only) and confirm each runs the expected subset and nothing else.

**Acceptance Scenarios**:

1. **Given** an engineer is iterating on a UI change, **When** they invoke the suite in UI-only mode, **Then** only UI-entrypoint variants execute.
2. **Given** an engineer is iterating on a backend change, **When** they invoke the suite in API-only mode, **Then** only API-entrypoint variants execute.
3. **Given** an engineer wants to run one scenario across both entrypoints, **When** they select that scenario by name, **Then** both its variants run and no others.

---

### Edge Cases

- **UI flow missing at test time**: if a scenario needs a UI action that does not yet exist, the test is not silently skipped — it fails loudly, and Story 3 resolves the gap by adding the flow. Skipping is reserved for scenarios intentionally declared API-only.
- **UI rendering lag vs. API response**: the programmatic entrypoint receives results synchronously; the UI must observe rendered state. The scenario's *success condition* is identical in both runs, but the waiting strategy differs — tests must tolerate UI eventual consistency without weakening the assertion.
- **Cross-variant isolation**: the API and UI variants of a scenario are never executed simultaneously against the same backend — they run in separate CI jobs, each with its own backend and virtual cluster. No cross-variant resource-name coordination is therefore required; the existing per-scenario naming scheme used by the API-entrypoint suite is sufficient.
- **Unexpected UI dialogs / toast notifications**: transient banners, error popups, or confirmation dialogs must not silently cause a UI test to pass because an action was intercepted. UI interactions must target stable, testable elements rather than positional clicks.
- **Authentication added later**: the suite today exercises an unauthenticated backend. If authentication is introduced, both entrypoints must pick up the new requirement without forcing each scenario to be rewritten.
- **External-state assertions**: scenarios that verify Kubernetes resources, HTTP endpoints on deployed apps, or database contents use the same external checks in both runs — the entrypoint only changes how actions are invoked, not how outcomes are verified.
- **UI-only capability surfaces**: if a scenario genuinely has no API counterpart (a behaviour that only exists in the UI layer), it is declared UI-only with the same explicit marker used for API-only exceptions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The E2E suite MUST support two interchangeable entrypoints for executing its scenarios: a programmatic-API entrypoint (the current one) and a UI entrypoint (new).
- **FR-002**: Every scenario currently covered by the programmatic E2E suite at the start of this work MUST be executable via both entrypoints by the end of this work, unless it is explicitly declared as single-entrypoint with a recorded reason.
- **FR-003**: The actions, pre-conditions, and assertions described by a scenario MUST be defined in a single place shared between the two entrypoint runs; duplicating scenario bodies for the UI variant is not allowed.
- **FR-004**: The UI MUST expose every user action required by the shared scenarios through normal product navigation (not hidden developer affordances). Any action missing today MUST be added as part of this feature.
- **FR-005**: The programmatic interface MUST expose every capability required by the shared scenarios. Any capability missing today MUST be added as part of this feature.
- **FR-006**: Test results MUST identify, for each scenario execution, which entrypoint was used, so that an API-only or UI-only failure is immediately distinguishable.
- **FR-007**: UI interactions MUST target stable, semantically meaningful elements (named roles, labels, or explicit test identifiers) rather than positional or structural selectors that break under incidental presentation changes.
- **FR-008**: UI-entrypoint tests MUST run against the same end-to-end stack used by the API-entrypoint tests (same deployed backend, same cluster resources, same external services) — no mocking of the application under test.
- **FR-009**: When a UI-entrypoint scenario fails, the suite MUST produce an artifact sufficient to debug without re-running locally (at minimum: a visual capture of the failing state and a step-by-step trace of the actions performed up to the failure).
- **FR-010**: The suite MUST allow a developer to run all scenarios, only API-entrypoint variants, only UI-entrypoint variants, or a single named scenario across both — through a consistent selection mechanism.
- **FR-011**: Adding a new scenario MUST by default produce coverage via both entrypoints; opting a scenario out (e.g. because it is intrinsically single-entrypoint) MUST be an explicit, reviewable decision with a recorded rationale, not the default.
- **FR-012**: Scenarios that verify external state (Kubernetes resources, HTTP responses from deployed applications, database contents) MUST perform those checks identically regardless of which entrypoint drove the preceding actions.
- **FR-013**: Each scenario execution MUST operate on uniquely named resources within its own CI job (as the existing API-entrypoint suite already does). Cross-variant collision protection is not required because the API and UI variants run in separate CI jobs against separate backends (see Assumptions).
- **FR-014**: The pass/fail outcome of a scenario MUST depend only on the observed behaviour of the system under test; a UI-entrypoint scenario MUST NOT pass merely because an interaction could not be located or an action was silently skipped.
- **FR-015**: The suite MUST continue to support the test environment topology currently used by the API-entrypoint suite (full live backend stack, virtual cluster, supporting services) without requiring a separate UI-only environment.
- **FR-016**: UI-entrypoint tests MUST run against Chromium as the single target browser, both locally and in CI; cross-browser execution (Firefox, WebKit) is explicitly out of scope for this feature.
- **FR-017**: UI-entrypoint scenarios MUST assert behaviour only (observable application state, DOM semantics, external-state outcomes). Pixel-level or screenshot-comparison assertions are explicitly out of scope; captured screenshots and traces exist solely as failure diagnostics per FR-009.
- **FR-018**: UI-entrypoint test failures MUST gate pull-request merges on the same authority as API-entrypoint failures — a failing UI variant blocks merge exactly as a failing API variant does. Advisory or nightly-only modes are not acceptable.
- **FR-019**: A failing UI-entrypoint test MUST be retried exactly once automatically before being reported as failed. The scenario is considered passed if either attempt succeeds. Diagnostic artifacts (FR-009) from the first attempt MUST still be recorded even when the retry succeeds, so that flakiness is observable and investigable. API-entrypoint tests are not retried.

### Key Entities

- **E2E Scenario**: A named description of an end-user workflow — pre-conditions, the sequence of user actions, and the observable outcomes that must hold. Defined once; executed by both entrypoints.
- **Test Entrypoint**: The mechanism that translates scenario actions into effects on the system. Two exist: the programmatic entrypoint (direct backend calls) and the UI entrypoint (driving the web interface). They are interchangeable from the scenario's point of view.
- **Scenario Action**: A single step within a scenario (e.g. "create environment", "deploy application", "trigger backup", "upgrade to version X"). Every action is expressible via both entrypoints.
- **Entrypoint Gap**: An action required by a scenario that one entrypoint cannot yet perform (for example: a UI that lacks a needed form, or an API that lacks a needed operation). Gaps are closed by extending the weaker entrypoint — not by shrinking the scenario.
- **Entrypoint Declaration**: An explicit marker on a scenario indicating it runs via both entrypoints (the default), or via only one with a recorded justification. Prevents silent skipping.
- **Diagnostic Artifact**: The evidence produced when a UI-entrypoint scenario fails — a visual capture of the failing state and a navigable trace of the actions leading to it — sufficient for remote debugging.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of E2E scenarios that existed at the start of this work are covered by both entrypoints at completion, or are explicitly declared single-entrypoint with a recorded reason. The count of "silently UI-missing" scenarios is zero.
- **SC-002**: An intentionally introduced UI-only regression (e.g. removing a button's label, changing a navigation path) causes the affected scenario's UI variant to fail while its API variant continues to pass — demonstrating the two entrypoints produce independent signals.
- **SC-003**: Adding a new E2E scenario requires editing exactly one scenario definition; no parallel edit to a UI-specific duplicate is needed for the scenario to run via both entrypoints.
- **SC-004**: Every failing UI-entrypoint run produces a diagnostic artifact (visual capture + action trace) available alongside the test report, with no additional local reproduction step required to start debugging.
- **SC-005**: A developer can run all scenarios, only the API-entrypoint subset, only the UI-entrypoint subset, or a single named scenario, using a single documented selection mechanism — verified by executing each of those four modes from a clean checkout.
- **SC-006**: Every UI flow required by the scenarios is reachable through the product's normal navigation (no hidden routes, developer-only query parameters, or backdoor forms).
- **SC-007**: The API-entrypoint and UI-entrypoint suites are executed as separate CI jobs, each against its own backend and virtual cluster; no cross-variant resource-name coordination is needed and neither job's outcome depends on the other's state.

## Assumptions

- The existing test environment topology (live backend stack, virtual cluster, supporting services) is re-used for the UI entrypoint; a separate UI-only environment is not needed.
- The API-entrypoint and UI-entrypoint suites execute as **separate CI jobs**, each provisioning its own backend and virtual cluster. They never run simultaneously against the same backend, so scenarios do not need to guard against cross-variant resource-name collisions.
- No end-user authentication exists on the application under test at the time of this work. If authentication is added later, the scenario definitions remain unchanged and the entrypoints absorb the new requirement behind their shared fixtures.
- External-state verifications (Kubernetes resources, HTTP checks against deployed applications, database content) are already entrypoint-agnostic and remain shared between the two runs as-is.
- "Identical test content" is interpreted as: same pre-conditions, same sequence of semantic actions, same assertions on system state. Timing/waiting strategies may differ between entrypoints as long as the success condition is identical.
- The user input names a specific tool family ("pytest-playwright") as an implementation hint. The spec treats this as a constraint on integration — the UI entrypoint should live inside the existing E2E test runner (same invocation, same test selection, same reporting) rather than as a separate standalone framework — and not as a statement about internal design.
- The set of scenarios in scope is the set currently under the existing E2E directory at the moment this work begins; scenarios added after work starts follow the "single-source-of-truth, both-entrypoints by default" rule from day one.
