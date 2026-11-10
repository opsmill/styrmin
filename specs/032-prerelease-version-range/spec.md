# Feature Specification: Accept prerelease application versions that fit a driver version's range

**Feature Branch**: `sas-591-prerelease-spec` (the spec directory number is independent of the branch name)

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "issue #591: [Support Infrahub beta releases with the standard application drivers](https://github.com/opsmill/styrmin/issues/591). Source PRD: [PRD comment on issue #591](https://github.com/opsmill/styrmin/issues/591#issuecomment-6762618486)."

## Background

A person who deploys an explicitly chosen Infrahub beta, such as `1.12.0b0`, with the standard `infrahub` and `infrahub-enterprise` drivers gets the error "Version 1.12.0b0 is not supported by the application driver". The driver versions declare the range `>=1.5,<2.0`. The range names no prerelease, and Styrmin matches a prerelease only when a clause of the range names one ([issue #591](https://github.com/opsmill/styrmin/issues/591), [PEP 440, handling of pre-releases](https://peps.python.org/pep-0440/#handling-of-pre-releases)). The refusal does not give a reason and does not list the supported ranges.

An earlier [comment of 2026-11-04](https://github.com/opsmill/styrmin/issues/591#issuecomment-6625117869) kept the matching rule and asked each driver to name a prerelease in its range. The PRD replaces that decision. [Fatih wrote in a Slack direct message on 2026-11-09](https://opsmillworkspace.slack.com/archives/D0C1JLMPB2S/p1794227533527739) (visible to the two participants only) that changing the driver is not the right solution and that Styrmin's version validation should accept prereleases.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deploy a prerelease with a standard driver (Priority: P1)

A person who runs a beta sandbox creates a deployment of a prerelease application version, such as `1.12.0b0` or `1.12.0-beta.1`, with a standard driver whose range names no prerelease. The person does not need a special driver build.

**Why this priority**: This is the problem in issue #591. Without it, the beta sandbox cannot use the standard drivers.

**Independent Test**: With the unchanged standard `infrahub-enterprise` driver, create a deployment of `1.12.0b0`, then one of `1.12.0-beta.1`, and view each deployment and its stored application version.

**Acceptance Scenarios**:

1. **Given** the unchanged standard `infrahub-enterprise` driver with the range `>=1.5,<2.0`, **When** the person creates a deployment of `1.12.0b0`, **Then** the deployment is created and reaches running.
2. **Given** the same driver, **When** the person creates a deployment of `1.12.0-beta.1`, **Then** the deployment is created and reaches running, and the stored application version is the string `1.12.0-beta.1`, as typed.
3. **Given** the same driver, **When** the person types the version as `1.12.0.b0`, **Then** the version is accepted.

---

### User Story 2 - Apply the same rule when changing a deployment (Priority: P2)

A person upgrades a running deployment to a prerelease, or pins a driver version while asking for a prerelease. The upgrade and the pin follow the same rule as the creation of a deployment.

**Why this priority**: A person who follows a beta to its release needs the same verdict at every step. A different verdict between creating and upgrading would be a new refusal with no stated reason.

**Independent Test**: Upgrade a running deployment of `1.11.9` to `1.12.0b0`. Then pin a driver version while asking for `1.12.0b0`. Then upgrade the deployment from `1.12.0b0` to `1.12.0`.

**Acceptance Scenarios**:

1. **Given** a running deployment of `1.11.9`, **When** the person upgrades it to `1.12.0b0`, **Then** the upgrade is accepted.
2. **Given** a running deployment of `1.11.9`, **When** the person pins a driver version while asking for `1.12.0b0`, **Then** the request is accepted.
3. **Given** a running deployment of `1.12.0b0`, **When** the person upgrades it to `1.12.0`, **Then** the upgrade is accepted.

---

### User Story 3 - A version outside the range is refused with the supported ranges (Priority: P3)

A person asks for a prerelease whose numbers do not fit any range of the driver. The refusal names the version and lists every supported range of the driver, so that the person can see what to change.

**Why this priority**: A refusal that gives no reason leaves the person guessing. This story turns that into an action the person can take.

**Independent Test**: Request `2.0.0b1` with a driver whose range is `>=1.5,<2.0` and read the error message.

**Acceptance Scenarios**:

1. **Given** the range `>=1.5,<2.0`, **When** the person requests `2.0.0b1`, **Then** the request is refused and no resource is created.
2. **Given** the same refusal, **When** the person reads the message, **Then** it names the version and lists every supported range of the driver, and it does not say that a range must name a prerelease.

---

### User Story 4 - Driver authors learn how a prerelease is ordered (Priority: P4)

A driver author reads the documentation to learn how a prerelease relates to a range. The documentation explains that PEP 440 orders a prerelease below its final release, and gives the range `>=1.12.0b0,<1.13` for a driver that must accept the prereleases of 1.12.0.

**Why this priority**: The rule has one result that surprises people: a range that starts at a final release refuses the prereleases of that release. Authors need to know this to write a correct range. It does not block people who deploy.

**Independent Test**: Read the driver-author page and find the rule, the ordering of a prerelease below its release, and the example range.

**Acceptance Scenarios**:

1. **Given** the driver-author documentation, **When** an author looks for how a range treats a prerelease, **Then** the page states the rule and the ordering and shows the range `>=1.12.0b0,<1.13`.

---

### Edge Cases

PEP 440 still orders a prerelease below its final release. The table shows the results of a local check with `packaging` 25.0 with prereleases allowed (taken from the PRD).

| Range | Version | Result |
|---|---|---|
| `>=1.5,<2.0` | `1.12.0b0`, `1.9.0rc1`, `1.12.0.dev3` | accepted |
| `>=1.5,<2.0` | `2.0.0b1`, `2.0.0rc1` | refused, a prerelease of the upper bound is not inside `<2.0` |
| `>=1.5,<2.0` | `1.5.0a1`, `1.5.0.dev1`, `1.4.0rc1` | refused, below the lower bound |
| `>=1.12.0,<1.13` | `1.12.0b0`, `1.9.0rc1`, `1.12.0.dev3` | refused, a prerelease of 1.12.0 is below 1.12.0 |

- Spellings: the same parser reads `1.12.0.b0`, `1.12.0.beta.1`, `1.12.0-beta.1` and `1.12.0_rc1` as prereleases. Checked locally with `packaging` 25.0.
- A version string that is not a PEP 440 version, such as `latest`, `develop` or `stable`, is refused as today.
- A request without a version uses the default version of the latest driver version. When that default is a prerelease that fits the range, it is accepted. This was not tested when the PRD was written.
- Several driver versions support the requested version: the existing rule for choosing among them is unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A prerelease application version MUST be accepted when its numbers fit a range of a driver version, at each of these places: creating a deployment, upgrading a deployment, pinning a driver version, and loading a driver (the check of its default version). The range does not need to name a prerelease. Check: one unit test at each place.
- **FR-002**: The same application version and the same range MUST give the same verdict at all four places. Check: one table of boundary cases, run through one shared check.
- **FR-003**: The application version MUST be stored as the person typed it. Check: create a deployment with `1.12.0-beta.1` and read the stored version.
- **FR-004**: A refusal MUST name the requested version and list every supported range of the driver. Check: the message in User Story 3.
- **FR-005**: A refusal message MUST NOT state that a range must name a prerelease. Check: a test on the message text.
- **FR-006**: A version that is not valid under PEP 440, such as `latest`, MUST be refused as today. Check: a unit test with `latest`.
- **FR-007**: Requests for stable versions MUST behave as before. Check: the existing test suite passes.
- **FR-008**: The documentation MUST explain the rule, the ordering of a prerelease below its final release, and the range `>=1.12.0b0,<1.13` for a driver that needs it. The glossary entries "Prerelease" and "Application version" MUST be updated, and a changelog entry MUST record the change. Check: review of the documentation, the glossary and the changelog fragment.

### Key Entities *(include if feature involves data)*

- **Application version** (existing): the text of the version a person typed. It is stored unchanged. Only the check against the range changes.
- **Driver version** (existing): its `application_supported_versions` range is unchanged. It is now matched with prereleases allowed.
- **Prerelease** (existing glossary entry, to be rewritten): the glossary text moves from "a range must name a prerelease" to "the numbers fit the range".

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the unchanged standard driver range, `1.12.0b0` and `1.12.0-beta.1` each create a deployment that reaches running.
- **SC-002**: The shared check and the four places (create, upgrade, pin, driver load) give 0 different verdicts across the boundary-case table.
- **SC-003**: Every refused request lists all supported ranges of the driver.
- **SC-004**: Requests for stable versions behave as before, and the existing test suite passes.

## Assumptions

- A person types the exact application version to deploy. A prerelease is not chosen by accident. This is based on how the CLI and API take a version in the issue's reproduction. It was not checked for every client.
- The version typed is the image tag spelling, and the person is responsible for it. How each driver's template uses the version was not checked.
- Creating a deployment and upgrading a deployment call the same driver version picker and the same pin check. The PRD states that this was checked in the repository code.
- The CLI and the UI show the text of the refusal message as the API returns it. How they show a message that lists several ranges is not known (PRD open question). The plan phase checks it.
- Whether the chart of the end-to-end test driver accepts a beta version string, and whether the UI variant of the end-to-end test can run User Story 1, is not known (PRD open question). The plan phase checks it.
- Whether User Story 1 is added to an existing end-to-end test or to a new one is decided in the plan phase. The constitution prefers extending an existing one. [PR #594](https://github.com/opsmill/styrmin/pull/594) gave reasons for a new one.
- No database schema, GraphQL schema, dependency, CI/CD or authentication change is needed. Only the text of an error changes on the API.
- The existing version error type is kept.

## Out of Scope

- Tags that are not versions: `latest`, `develop`, `stable`. They need their own issue, as Fatih asked for non-semver versions in his message.
- Changing the ranges of the standard drivers. The unchanged range accepts `1.12.0b0`.
- A request-level opt-in for prereleases.
- A way for a driver author to forbid prereleases.
- Seeding, the exact application-version check and backups of the beta sandbox. The issue states that it did not verify them.
- Rework of [PR #594](https://github.com/opsmill/styrmin/pull/594) beyond what this feature needs: its tests check the old rule and are to be reworked, and its refusal message is extended.

## Governance Gates Crossed

Source: the "Ask First" list in `AGENTS.md`.

- Database schema or migration change: none
- GraphQL schema modification: none, only error text
- New dependency: none
- CI/CD workflow change: none
- Authentication or authorization change: none
