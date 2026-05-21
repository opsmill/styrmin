# Feature Specification: Driver Detail Page Redesign (Tabbed Layout)

**Feature Branch**: `012-driver-detail-tabs`
**Created**: 2026-05-21
**Status**: Draft
**Input**: User description: "Redesign the application driver detail page using a tabbed layout — left rail of driver versions + vertical divider + right pane with Overview / Parameters / Components / Actions / Source tabs. Replace raw JSON dumps with structured rendering."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Inspect a driver version's parameters (Priority: P1)

A **platform engineer** opens an **application driver**'s detail page to verify which parameters the latest **driver version** exposes (name, kind, required status, default value). Today this is painful because all versions render at once and parameters are mixed with raw JSON dumps of other content.

**Why this priority**: Confirming what a **driver version** declares is the most common reason a platform engineer lands on this page — when registering a new driver, when reviewing a teammate's driver change, or when debugging why a deployment is asking for an unexpected parameter. Without this slice, the page provides no value beyond the existing experience.

**Independent Test**: Open an **application driver** with three or more **driver versions**. Confirm the latest version is selected by default, and the right pane shows a structured parameters table for that version without scrolling past other versions' content.

**Acceptance Scenarios**:

1. **Given** an **application driver** with three **driver versions** at distinct registration timestamps, **When** the user navigates to that driver's detail page, **Then** the left rail lists the three versions newest-first, the most recent version is selected, and the right pane shows that version's structured parameters table (one row per parameter with name, label, kind, required-flag, default).
2. **Given** a **driver version** with no declared parameters, **When** that version is selected, **Then** the Parameters tab shows the message "No parameters declared" — no empty table header is rendered.

---

### User Story 2 — Inspect a driver version's components and actions (Priority: P2)

A **platform engineer** needs to understand which **components** a **driver version** declares and which **actions** it exposes. Today these arrive as raw JSON blobs; this story replaces them with structured rendering.

**Why this priority**: Once parameters are scannable (P1), components and actions are the next-most-asked questions ("does v1.3.0 still ship the sidecar?", "what action lets me flush the cache?"). Lower priority than P1 because the data is at least visible today (as JSON), just not scannable.

**Independent Test**: Open a **driver version** that declares at least one **component** and at least one **action**. Switch to the Components tab, then the Actions tab. Confirm each renders as structured rows or cards, and that no raw JSON block appears on the page.

**Acceptance Scenarios**:

1. **Given** a **driver version** declaring three **components**, **When** the user switches to the Components tab, **Then** each component is rendered as a row showing its name and the readable fields the system extracts from its declaration — and no `<pre>` block of JSON output appears.
2. **Given** a **driver version** declaring two **actions**, **When** the user switches to the Actions tab, **Then** each action is rendered as a card with its name, description, and location.
3. **Given** a **driver version** whose `components` declaration is absent or unexpectedly shaped, **When** the user views the Components tab, **Then** the message "This version declares no components" is shown — no JSON fallback is rendered.

---

### User Story 3 — Trace where a driver version came from (Priority: P3)

A **platform engineer** wants to know which repository, branch, and subpath a **driver version** was sourced from (or which local path, for local-source versions). Today they have to click out to GitHub or read the URL fragments shown in the version header.

**Why this priority**: Source-tracing is asked less frequently than parameter/component inspection, but when it's asked it's load-bearing (security review, audit, "where did this come from?"). Lower priority because the page already shows minimal source information today; this story makes it scannable and complete.

**Independent Test**: Open a **driver version** with a known git source. Switch to the Source tab. Confirm the repository URL, branch (if applicable), and subpath are visible without leaving the page.

**Acceptance Scenarios**:

1. **Given** a git-sourced **driver version**, **When** the user switches to the Source tab, **Then** the repository URL, branch, and subpath (when set) are visible.
2. **Given** a local-source **driver version** (`sourceType` is `local`), **When** the user switches to the Source tab, **Then** the local source path is visible, and branch is not rendered.
3. **Given** a git-sourced **driver version** in the left rail, **When** scanning the rail, **Then** the row shows a "git" indicator; for a local-source version the row shows "local".

---

### Edge Cases

- **Driver with zero versions.** The left rail shows the message "No versions yet"; the right pane shows an empty state including the role-gated "Add Version" action; tabs are not rendered.
- **Selected version no longer exists after auto-refresh.** If the version the user was viewing has been removed server-side between refreshes, the page silently falls back to the new newest version without error or toast.
- **New version appears during auto-refresh.** The version list updates to include the new entry; the currently-selected version remains selected — the page does not auto-jump to the new latest.
- **Empty declarations.** When a **driver version** has zero parameters, zero components, or zero actions, the corresponding tab shows a tab-specific empty-state message and does not render an empty table header.
- **Long parameter list.** When a **driver version** declares many parameters, the page scrolls naturally — no internal scrolling region is introduced inside the tab.

## Requirements *(mandatory)*

### Functional Requirements

**Listing and selecting versions**

- **FR-001**: System MUST list all **driver versions** for an **application driver** in a left rail in newest-first order by registration time, with the most recent version selected by default on page load.
- **FR-002**: Users MUST be able to switch the active **driver version** by clicking a row in the left rail; the right pane MUST update without navigating to a new route.
- **FR-003**: System MUST display, on each **driver version** row, a relative-time label (e.g. "2 days ago") derived from the version's registration time.
- **FR-004**: System MUST visually distinguish git-sourced **driver versions** from local-source ones in the left rail.

**Tabbed right pane**

- **FR-005**: System MUST present the selected **driver version**'s content across five tabs: Overview, Parameters, Components, Actions, Source.
- **FR-006**: Users MUST be able to switch tabs by clicking a tab header.
- **FR-007**: Switching the active **driver version** MUST preserve the currently active tab; switching the active tab MUST preserve the currently selected **driver version**.

**Structured rendering**

- **FR-008**: System MUST render the selected **driver version**'s parameters as a structured table whose columns identify name, label, kind, required-flag, and default value.
- **FR-009**: System MUST render the selected **driver version**'s components as structured rows, never as raw JSON output.
- **FR-010**: System MUST render the selected **driver version**'s actions as structured cards (name, description, location), never as raw JSON output.
- **FR-011**: System MUST mark parameters whose default value is absent (null or undefined) as required.

**Source visibility**

- **FR-012**: For a git-sourced **driver version**, the Source tab MUST display the repository URL, branch (when set), and subpath (when set).
- **FR-013**: For a local-source **driver version**, the Source tab MUST display the local source path and MUST NOT render branch metadata.

**Preserved behaviour**

- **FR-014**: System MUST preserve the existing periodic auto-refresh of driver data and the user-facing auto-refresh indicator.
- **FR-015**: System MUST gate the "Add Version" action so it is only visible to users with at least read-write permission on the **application driver**.
- **FR-016**: System MUST allow users to navigate back to the Drivers list via the page breadcrumb.

**Empty states**

- **FR-017**: When the selected **driver version** declares zero parameters, the Parameters tab MUST show an empty-state message and MUST NOT render an empty table header.
- **FR-018**: When the selected **driver version** declares zero components or when the components declaration is unexpectedly shaped, the Components tab MUST show an empty-state message and MUST NOT render raw JSON.
- **FR-019**: When the selected **driver version** declares zero actions, the Actions tab MUST show an empty-state message.
- **FR-020**: When the **application driver** has zero **driver versions**, the page MUST show an empty state with the role-gated "Add Version" action and MUST NOT render tabs.

**Refresh resilience**

- **FR-021**: If the selected **driver version** is removed server-side between refreshes, the page MUST silently fall back to the new newest version.
- **FR-022**: If a new **driver version** appears during refresh, the page MUST surface it in the left rail without changing the user's current selection.

**Supporting data exposure**

- **FR-023**: The system's read API for **application drivers** MUST expose the registration time of each **application driver** and each **driver version** so the listing requirements above can be satisfied.

### Key Entities

- **Application driver**: The root entity of the page. A unique, versioned **application driver** owns a set of **driver versions**. Gains visibility of its registration time on the read API.
- **Application driver version**: The entity selected by the user via the left rail. Owns the helm chart reference, parameters, components, actions, and source metadata that the right pane renders. Gains visibility of its registration time on the read API.
- **Parameter**: A declared input on a **driver version**, surfaced in the Parameters tab as a row with name, label, kind, required-flag, default.
- **Component**: A driver-declared sub-part of an application, surfaced in the Components tab as a structured row. Only the **driver-declared** shape is surfaced; runtime observations (pods, live containers) are out of scope for this page.
- **Action**: A driver-declared operation surfaced in the Actions tab as a card showing name, description, and location.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A platform engineer can locate any declared parameter (name, kind, default, required status) for any **driver version** in under 5 seconds, regardless of how many other versions the driver has.
- **SC-002**: Zero raw JSON output appears on the rendered page for any **driver version**'s content tabs. Verifiable by an automated check that no preformatted JSON block exists in the Overview / Parameters / Components / Actions / Source panels.
- **SC-003**: The page renders without overflow or layout breakage for an **application driver** with up to 20 **driver versions** — the left rail scrolls within its column while the right pane is unaffected.
- **SC-004**: A platform engineer can identify the source location (repository or local path; branch when applicable) of any **driver version** without leaving the page.
- **SC-005**: Switching between any two **driver versions** of the same **application driver** updates the right pane in under 1 second on a typical engineering laptop, with no fresh data load required from the server.

## Assumptions

- Platform engineers have **read-write** permission to add **driver versions** to an **application driver**; **read-only** users can browse the page but will not see the "Add Version" affordance.
- Newest-by-registration-time is an acceptable proxy for "latest" **driver version**. In normal operation drivers are registered in chronological order matching their semver progression. Edge cases (re-registering an older version after a newer one) may misorder; users can scan the version string to confirm.
- The existing data refresh interval for this page (10 seconds) is acceptable and will not change.
- Per-version "Used by N deployments" data, action input declarations, component runtime observations, and latest-commit metadata are **out of scope** for this feature — they are not rendered, even as placeholders.
- Triggering an **action** (running it) and editing a **driver version** inline are out of scope; the existing "Add Version" flow remains the only mutation path on the page.
- Filter / search within the Parameters table is out of scope.
- No changes to the Drivers list page or any unrelated page are introduced by this feature.
