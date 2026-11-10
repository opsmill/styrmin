# Implementation Plan: Accept prerelease application versions that fit a driver version's range

**Branch**: `sas-591-prerelease-spec` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/032-prerelease-version-range/spec.md`

## Summary

A person who asks for a prerelease application version, such as `1.12.0b0`, is refused by the standard drivers today, because their range `>=1.5,<2.0` names no prerelease. The change makes Styrmin's own range check accept a prerelease when its numbers fit the range, at every place that checks a version: creating, upgrading, pinning and loading a driver. The drivers and the driver model do not change. The refusal for a version outside the range lists every supported range of the driver and no longer explains a prerelease rule.

Technical approach, from [research.md](research.md):

- One new function, `version_fits_range`, calls the `prereleases=True` argument that `packaging` already provides (D1, D3). The three places that test a range call it.
- The refusal text reuses the range list of the open pull request #594, which this branch takes over by cherry-picking its commit and then reworking it (D2, D5).
- End-to-end coverage extends `test_deploy_app.py` and reuses the session `simple-app` driver with its unchanged range (D6).

What the maintainers still have to decide: what happens to pull request #594 itself (research, "Items for the maintainers").

## Technical Context

**Language/Version**: Python 3.14+ (backend). No frontend, SDK or CLI code change.

**Primary Dependencies**: `packaging` 25.0 (already installed; no new dependency), Pydantic v2 (driver model validator), Strawberry GraphQL (unchanged, error text only).

**Storage**: PostgreSQL via SQLModel. No change, no Alembic revision (data-model.md, "Persistence").

**Testing**: pytest for unit tests (`backend/tests/unit/`), pytest E2E on a vCluster (`backend/tests/e2e/`), the docs build with `pnpm build` in `docs/`.

**Target Platform**: the Styrmin backend service on Kubernetes (unchanged).

**Project Type**: web service (backend, GraphQL API) with a CLI and a frontend that only display the message.

**Performance Goals**: none. The check parses one version and a few ranges per request.

**Constraints**: a stable version must give the same verdict as before (FR-007). The stored range text of a driver version must not change, because it is part of the driver version's identity key. The application version is stored as typed.

**Scale/Scope**: about 3 changed code locations, 1 new module, 1 reworked message helper, 1 documentation section, 1 glossary entry, 1 changelog fragment, 1 new E2E test node in an existing file.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design (see the end of this section).*

Source: [dev/constitution.md](../../dev/constitution.md) version 1.4.1.

| Principle | Result | Evidence |
|---|---|---|
| I. Declarative State Reconciliation | Pass | No change to desired or current state or to reconciliation. Only a validation verdict changes. |
| II. Driver-Based Deployment | Pass | The drivers and the driver model do not change. The fix is in Styrmin's own version check (research D1; the user's design preference for Styrmin). |
| III. Layered Architecture | Pass | The shared check lives in the service layer (`services/version_range.py`). The pydantic driver model imports it, as it already imports `services.exceptions`. |
| IV. Type Safety and Typed Errors | Pass | `InvalidVersionError` stays. Type hints on the new function. No union types for errors. |
| V. Test-First Development | Pass with action | A unit test per place, and an E2E node that must be run to a pass with recorded evidence (quickstart step 3). The E2E extends `test_deploy_app.py` instead of booting a new stack (research D6). |
| VI. Format and Lint Before Commit | Pass with action | `uv run invoke format lint` in the final tasks. |
| VII. Documentation Accuracy | Pass with action | The driver-author page, the glossary and a changelog fragment are in the task list (research D8). |

Governance gates ([spec.md](spec.md), "Governance Gates Crossed"): no database schema change, no GraphQL schema change, no new dependency, no CI change, no authentication change. No "Ask First" item is crossed.

GraphQL propagation tests (Constitution V): not required, because no field, argument, input type or mutation changes ([contracts/refusal-messages.md](contracts/refusal-messages.md)).

**Re-check after Phase 1 design**: unchanged. The design adds one module and changes no layer boundary.

## Project Structure

### Documentation (this feature)

```text
specs/032-prerelease-version-range/
├── plan.md                         # This file
├── research.md                     # Phase 0 output
├── data-model.md                   # Phase 1 output
├── quickstart.md                   # Phase 1 output
├── contracts/
│   └── refusal-messages.md         # Phase 1 output: the text of the error
├── checklists/
│   └── requirements.md             # Spec quality checklist (specify phase)
└── tasks.md                        # Created by the tasks phase
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   └── services/
│       ├── version_range.py                      # NEW: version_fits_range()
│       ├── deployment.py                         # CHANGE: picker, pin check, refusal helper
│       └── driver/models/resources/driver.py     # CHANGE: validate_default_version
└── tests/
    ├── unit/services/
    │   ├── test_version_range.py                 # NEW: the boundary table
    │   ├── test_driver_version_resolution.py     # CHANGE (from #594): picker verdicts
    │   ├── test_unsupported_version_message.py   # CHANGE (from #594): new rule and message
    │   └── driver/test_default_version.py        # NEW: driver-load verdicts
    └── e2e/
        └── test_deploy_app.py                    # CHANGE: one new node, session driver
docs/docs/drivers/
├── creating-a-driver.md                          # CHANGE (from #594): the new rule
└── loading-drivers.md                            # CHANGE (from #594): link text
CONTEXT.md                                        # CHANGE: "Prerelease", "Application version"
changelog/591.changed.md                          # CHANGE (from #594): new text
```

Files that #594 adds and this change removes or replaces: `backend/tests/e2e/test_prerelease_version.py` (replaced by the new node in `test_deploy_app.py`, because the new rule needs no second driver build) and the helper `publish_simple_app_driver_build` in `backend/tests/e2e/helpers/drivers.py` (removed if no other test uses it, otherwise kept).

**Structure Decision**: the existing layout of the `backend/` package and its `tests/` tree. One new service module with no dependencies other than `packaging`, so that both `deployment.py` and the driver model can import it without a cycle (`services/__init__.py` holds only a docstring).

## Design

### The shared check

`version_fits_range(version: Version, supported_versions: str) -> bool` returns `SpecifierSet(supported_versions).contains(version, prereleases=True)`. It takes a parsed `Version`, so each caller keeps parsing the string the way it does today and the outcome for a string that is not a PEP 440 version does not change (research D4).

### The three call sites

| Place | Today | After |
|---|---|---|
| `_resolve_latest_matching_version` (`deployment.py`) | `target in SpecifierSet(...)` | `version_fits_range(target, ...)` |
| `_ensure_pin_supports_version` (`deployment.py`) | `Version(version) not in SpecifierSet(...)` | `not version_fits_range(Version(version), ...)`, and the message gets the driver's ranges (contract, message 2) |
| `validate_default_version` (`driver.py`) | `Version(self.default_version) not in specifier` | `not version_fits_range(Version(self.default_version), self.supported_versions)` |

Create and upgrade reach the first two through the same helpers (`deploy_application` and `update_deployment_version`), so the four places in the spec map to these three call sites.

### The refusal

`_unsupported_version_error(application_driver, version)` (from #594) builds message 1 of the contract. `_prerelease_explanation` is deleted. The pin helper receives the application driver so that it can list the ranges (message 2).

### What does not change

The latest-wins ordering of driver versions, the stored range text and its fingerprint identity, the stored application version, the error code, the GraphQL schema, the SDK, the CLI and the frontend.

### Risks

- **A range now accepts more versions.** `>=1.5,<2.0` now accepts `1.9.0rc1`. This is the intended rule (spec, FR-001). The documentation says so (research D8).
- **Latest-wins with overlapping ranges.** A driver version with `>=1.12.0b0,<1.13` and one with `>=1.5,<2.0` both fit `1.12.0b0`. The existing rule picks the highest driver `version`, so nothing new is needed.
- **The UI Deploy form may reject a prerelease string.** Not verified (research D6). The E2E node is `api_only` with the reason if the form rejects it, and the form is then recorded as a separate issue.
- **The cherry-pick of #594 applies without conflict today** (checked with `git merge-tree`). It may stop applying if `develop` changes `deployment.py` or `CONTEXT.md` first.

## Complexity Tracking

No constitution violation. No entry.
