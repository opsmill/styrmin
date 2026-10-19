# Implementation Plan: Run the Actions of Driver Versions Loaded from a Local Directory

**Branch**: `fac/actions-local-drivers-qlmex` | **Date**: 2026-10-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/029-local-driver-actions/spec.md`

## Summary

Driver versions loaded with `load-local-version` register no Prefect flow for their actions, so their hooks are skipped without an error and an upgrade falls back to a plain update ([#372](https://github.com/opsmill/styrmin/issues/372)). This plan:

- registers the actions of local driver versions with the key that ADR-080 already uses for git driver directories ([R-003](research.md#r-003-registration-key-of-a-local-driver-versions-actions));
- runs each local action from the version's `source_path` in the action Job's image, behind a Prefect pull step that checks the provenance fingerprint before Prefect imports `actions.py` ([R-001](research.md#r-001-how-an-action-of-a-local-driver-version-runs-the-actionspy-at-its-path), [R-004](research.md#r-004-the-provenance-fingerprint-at-a-path-in-the-loader-and-in-the-actions-job));
- makes the hook step show the check's error by reading the first error log of a crashed flow run ([R-002](research.md#r-002-how-the-error-of-the-check-reaches-the-hook-step));
- replaces the hook lookups with one service function that fails when a declared action has no registered flow ([R-007](research.md#r-007-hook-resolution-in-one-service-function), [R-008](research.md#r-008-recording-a-missing-registration-that-the-apply_state-flow-finds));
- checks the upgrade hooks in `update_deployment_version` before anything is written, so a failed upgrade can be requested again ([R-009](research.md#r-009-running-the-same-upgrade-again-after-it-failed-for-a-missing-registration-fr-007));
- registers missing actions on every load ([R-010](research.md#r-010-registering-missing-actions-on-a-repeated-load-fr-006)).

No database, GraphQL, Helm, SDK, CLI or frontend change.

## Technical Context

**Language/Version**: Python 3.14+ (backend).

**Primary Dependencies**: Prefect 3.8.6 (pull steps, deployments, flow run logs), SQLModel and SQLAlchemy (async), Pydantic v2, Loguru. No new dependency.

**Storage**: PostgreSQL through SQLModel. No schema change and no Alembic revision: `ApplicationDriverVersion.source_path`, `content_hash` and the `Action` rows already exist. One repository method is added (`ActionRepository.list_by_driver_version`).

**Testing**:

- pytest unit tests;
- functional tests against a real Prefect server (`prefect_test_harness`, as in `backend/tests/functional/test_user_action_registration.py`);
- E2E tests on a per-session vCluster (`backend/tests/e2e/`).

**Target Platform**: Kubernetes. The Styrmin server and the agent run from the Styrmin image; action Jobs run in the `user-work-pool` Kubernetes work pool.

**Project Type**: web service (backend only for this change).

**Performance Goals**:

- A repeated load makes one Prefect lookup per declared hook and mode (at most five) and no write when nothing is missing.
- The check in the action's Job reads three files.
- A crashed hook makes one extra log read.

**Constraints**:

- No GraphQL, database, Helm chart, work pool job template, SDK, CLI or frontend change (spec, Constraints).
- The check must run before Prefect imports `actions.py` (FR-003).
- Prefect resolves `{{ ... }}` in pull step inputs, so no input may carry a value that a user or driver author can choose freely (R-005).

**Scale/Scope**: five bundled drivers with three actions each; at most five hook and mode pairs per driver version.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How the plan meets it |
|-----------|--------|-----------------------|
| §I Declarative state reconciliation | Pass | A repeated load registers only missing actions and writes nothing to Prefect when none is missing (R-010). The request check of R-009 changes nothing when it fails. |
| §II Driver-based deployment | Pass | Local driver versions now run every action they declare. A missing registration fails the hook instead of skipping it. |
| §III Layered architecture | Pass | Hook resolution is a service function (`services/driver/hooks.py`) that the remediation service and the deployment service call. The repository gets one method. The pull step (workflow layer) calls only the fingerprint function in `services/driver/hash.py`, which has no database or API dependency. |
| §IV Typed errors | Pass | Three new `DriverError` subclasses: `DriverFilesNotFoundError`, `DriverFingerprintMismatchError` and `ActionNotRegisteredError` ([contracts/errors.md](contracts/errors.md)). No union type is used for errors. |
| §V Test-first, E2E definition of done | Pass | New E2E module `test_local_driver_actions.py` covers user stories 1 to 3 and must be observed to pass locally with the evidence the constitution lists. Functional tests use a real Prefect server. No GraphQL change, so no propagation test. |
| §VI Format and lint | Pass | `uv run invoke format lint` before each commit. |
| §VII Documentation accuracy | Pass | The plan includes these documentation updates in the same change: `docs/docs/drivers/loading-drivers.md`, `dev/guides/driver-iteration.md`, `dev/knowledge/backend/hooks-and-actions.md`, a new ADR-081, an amendment of ADR-053, `CONTEXT.md` and a towncrier fragment (FR-008, FR-009). |

**Governance gates**: none crossed.

- No database schema or migration change.
- No GraphQL schema change.
- No new dependency.
- No CI workflow change: the new E2E module carries the existing `shard_general` marker, and its derived image is built by a session fixture, not by CI.
- No authentication or authorization change: actions keep the action token ([ADR-059](../../dev/adr/0059-driver-action-api-tokens.md)).

**Post-design re-check**: the design in Phase 1 keeps every row above as Pass. The request check of R-009 saves a task without a flow run, as `delete_deployment` already does; this needs no schema change because `Task.prefect_flow_run_id` and `Task.instance_id` are nullable.

## Design

### Load: register the actions of every driver version (FR-001, FR-006)

`load_application_driver_from_object` (`services/applications.py`) calls a new `ensure_action_registrations` on both paths: after the identity lookup finds an existing version, and before it creates a new one. See [contracts/action-registration.md](contracts/action-registration.md).

- `ActionsWorkflowBuilder` (`services/user.py`) accepts a `GitSource` or a `LocalSource`. For a `LocalSource`, it builds a `LocalDriverActionWorkflowDefinition` (`workflows/models.py`): entrypoint `actions.py:<function>`, the action's `image`, and one pull step `styrmin_backend.workflows.local_driver.check_local_driver` with the path, the full `content_hash` and the three driver file names.
- The registration and lookup key uses `action_directory_of(source_type, source_path)` (`services/driver/labels.py`) as the ADR-080 driver directory.
- Before it registers a local version's actions, the load refuses a path that contains `{` or `}` (R-005).

### Action Job: check the files, then run them (FR-002, FR-003, FR-004)

`check_local_driver` (`workflows/local_driver.py`, new) runs as the deployment's only pull step. See [contracts/local-driver-check.md](contracts/local-driver-check.md).

- It raises `DriverFilesNotFoundError` when the path or a required file is missing.
- It raises `DriverFingerprintMismatchError` when `compute_driver_directory_fingerprint` differs from the expected hash.
- Otherwise it returns `{"directory": <path>}`, and Prefect imports `actions.py` from the path.
- It reads the image for the message from the Prefect API only when it fails (R-006).

`run_deployment_or_fail` (`agent/tasks/utils.py`) adds the first `ERROR` log of a crashed flow run to its error (R-002), so the hook step records the check's message.

### Hooks: resolve, or fail with a typed error (FR-005)

`services/driver/hooks.py` (new) holds `resolve_hook_flow`, `resolve_setup_hooks` and `resolve_upgrade_hooks`. See [contracts/hook-resolution.md](contracts/hook-resolution.md).

- `InstanceCreationStrategy` and `InstanceUpdateStrategy._handle_upgrade` (`services/reconciliation/remediation.py`) call them instead of `get_user_action_deployment_id`.
- `instantiate_application` and its four unit tests are deleted (R-007).
- `apply_state` (`agent/tasks/orchestration.py`) records an `ActionNotRegisteredError` from planning on the failed hook step (R-008).

### Upgrade request: check before writing (FR-007)

`update_deployment_version` (`services/deployment.py`) calls `resolve_upgrade_hooks` for the target driver version when the application version changes, before its first write. On `ActionNotRegisteredError` it saves a failed `upgrade_instance` task with a failed hook step, leaves the deployment unchanged, and returns the task (R-009, [contracts/hook-resolution.md](contracts/hook-resolution.md#request-check-in-update_deployment_version)).

### Errors

Three typed errors in `services/driver/exceptions.py`; their messages are part of the contract because SC-003 relies on them ([contracts/errors.md](contracts/errors.md)).

### Documentation (FR-008, FR-009)

| File | Change |
|------|--------|
| `docs/docs/drivers/loading-drivers.md` | Actions of a local driver run from the same path in the action's image; what a custom `image:` must hold; the three errors and how to fix each; loading a driver again registers missing actions. |
| `dev/guides/driver-iteration.md` | After editing an action on the dev stack, run `docker compose build` and load the driver again. Fix two stale statements found during research: the values template name comes from `STYRMIN_DRIVER_VALUES_TEMPLATE`, and the hash framing is the name, a zero byte and an 8-byte big-endian length. |
| `dev/knowledge/backend/hooks-and-actions.md` | Local registration, the check pull step, hook resolution, the crash log in hook step errors, the request check. |
| `dev/adr/0081-local-driver-actions-run-from-the-path-in-the-job-image.md` (new) | The decisions of the PRD and of R-001 to R-010, with the rejected alternatives. |
| `dev/adr/0053-driver-version-provenance-fingerprint.md` | Amendment note: a repeated load registers missing actions; a local version's action checks the files at its path against the fingerprint. |
| `CONTEXT.md` | Entries Action and Provenance fingerprint. |
| `changelog/372.fixed.md` | Load local drivers again; deployments created from them before the fix never ran their setup actions. |

## Project Structure

### Documentation (this feature)

```text
specs/029-local-driver-actions/
├── spec.md
├── plan.md               # This file
├── research.md           # Phase 0
├── data-model.md         # Phase 1
├── quickstart.md         # Phase 1
├── contracts/
│   ├── action-registration.md
│   ├── local-driver-check.md
│   ├── hook-resolution.md
│   └── errors.md
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── agent/tasks/
│   ├── orchestration.py          # apply_state: record ActionNotRegisteredError on the hook step (R-008)
│   └── utils.py                  # run_deployment_or_fail: first error log of a crashed run (R-002)
├── repository/action.py          # ActionRepository.list_by_driver_version
├── services/
│   ├── applications.py           # ensure_action_registrations on both load paths; delete instantiate_application
│   ├── deployment.py             # update_deployment_version: request check (R-009)
│   ├── reconciliation/remediation.py  # strategies call services/driver/hooks.py
│   ├── user.py                   # ActionsWorkflowBuilder accepts GitSource or LocalSource
│   └── driver/
│       ├── exceptions.py         # three typed errors
│       ├── hash.py               # compute_driver_directory_fingerprint
│       ├── hooks.py              # new: resolve_hook_flow, resolve_setup_hooks, resolve_upgrade_hooks
│       ├── labels.py             # action_directory_of
│       └── loaders.py            # local loader uses compute_driver_directory_fingerprint
└── workflows/
    ├── local_driver.py           # new: check_local_driver pull step
    └── models.py                 # LocalDriverActionWorkflowDefinition

backend/tests/
├── unit/
│   ├── services/driver/test_hash_directory.py        # fingerprint at a path
│   ├── services/driver/test_hooks.py                 # hook resolution
│   ├── services/test_local_action_registration.py    # builder and ensure_action_registrations
│   ├── services/test_update_version_hook_check.py    # request check (R-009)
│   ├── workflows/test_local_driver_check.py          # pull step
│   └── agent/test_run_deployment_crash_log.py        # crash log in the error
├── functional/test_user_action_registration.py       # extended: local registrations, five bundled drivers, repeated load
└── e2e/
    ├── fixtures/drivers/local-actions/               # new fixture driver
    └── test_local_driver_actions.py                  # new E2E module

docs/docs/drivers/loading-drivers.md
dev/guides/driver-iteration.md
dev/knowledge/backend/hooks-and-actions.md
dev/adr/0081-local-driver-actions-run-from-the-path-in-the-job-image.md
dev/adr/0053-driver-version-provenance-fingerprint.md
CONTEXT.md
changelog/372.fixed.md
```

**Structure Decision**: backend-only change inside the existing layout (`backend/styrmin_backend`, `backend/tests`), with the documentation pages listed above. Test file names are proposals; tasks may place tests in existing files that cover the same module.

## Testing Strategy

What a test asserts is what a user views: which actions ran, which step failed, and the text of its error. Tests do not assert how a flow is registered, except where the registration is the observable result (FR-001 verification).

| Requirement | Unit | Functional (real Prefect) | E2E |
|-------------|------|---------------------------|-----|
| FR-001 | builder output for a local source | five bundled drivers loaded locally: three registrations each, tagged with the fingerprint and `directory/<path>` | user story 1: registrations exist |
| FR-002 | pull step returns the path; two paths with the same files register two deployments | two local paths, same files: two deployments | user story 1: markers in the logs; user story 2: the action ran in its `image:` |
| FR-003 | mismatch raises with the message of [errors.md](contracts/errors.md) | — | user story 2: `hook:setup:pre` fails with the message |
| FR-004 | missing path and missing `actions.py` raise | — | user story 2: server-only copy fails with the message |
| FR-005 | `resolve_hook_flow` raises; remediation raises; `apply_state` records the hook step | — | user story 3: failed `hook:upgrade:core` step |
| FR-006 | `ensure_action_registrations` registers only missing pairs | delete registrations, load again: they exist again; a second load writes nothing | user story 3: load again repairs |
| FR-007 | request check: failed task, deployment unchanged | — | user story 3: same request runs the upgrade |
| R-002 | crashed run with an error log, without one, and when the read fails | — | user story 2: the hook step shows the check's message |
| R-005 | path with `{` refused for a driver with actions, accepted without actions | — | — |

E2E module: `backend/tests/e2e/test_local_driver_actions.py`, markers `ci`, `shard_general`, `api_only(reason="The change is in which actions run; the deploy and upgrade UI flows are covered by test_deploy_app")`. Run with `--pdb` per AGENTS.md. Design in [R-011](research.md#r-011-e2e-design).

Existing tests to re-run because their path changes: `backend/tests/unit/services/reconciliation/test_remediation.py`, `backend/tests/unit/workflows/test_user_action_registration.py`, `backend/tests/functional/test_user_action_registration.py`, `backend/tests/e2e/test_driver_reload_identity.py` (its fixture declares actions, which are now registered), `backend/tests/e2e/test_driver_version_reselection.py`, `backend/tests/e2e/test_task_steps.py` and `backend/tests/e2e/test_deploy_app.py`.

## Risks

| Risk | Mitigation |
|------|------------|
| The engine's error log is not yet in the API when `run_deployment_or_fail` reads it. | Prefect drains its log queue at process exit (R-002). The E2E test of user story 2 asserts the message on the hook step. If the log is missing, the error keeps today's text. |
| A custom action image holds a `styrmin_backend` without the check step. | The Job crashes with `ModuleNotFoundError`, which the hook step shows (R-002). The documentation states the requirement (R-013). |
| A registration disappears between the request check and the plan. | `apply_state` still fails the hook step (R-008). The deployment then needs the usual recovery for a failed upgrade. |
| An existing E2E test relied on a skipped hook. | Every E2E driver load except `test_driver_reload_identity.py` is from git and registers its actions today. That test deploys nothing. |
| The derived image of the E2E test collides between concurrent CI jobs on one runner. | Its tag and its driver path include the session id. The session removes it at the end. |

## Complexity Tracking

No constitution violation to justify.
