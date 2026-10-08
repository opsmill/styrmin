# Baseline: Backup Tests Before the Backup History Change (#304)

## Overview

Every test in the files that this change touches passes before the change. No test fails at the baseline. These results come from tasks T001 and T002 in [tasks.md](tasks.md), run on 2026-10-08 against commit `1681b1ac`, before any feature code changed.

## Code generation (T001)

- `uv run invoke generate` exits 0 and leaves no git diff when Node 22 (v22.23.3) is first on `PATH`.
- With the system Node 18.19.1, the frontend step fails. `invoke` runs `pnpm codegen` in a pseudo-terminal (`pty=True` in `tasks/__init__.py`), and in a pseudo-terminal `graphql-codegen` exits 1 without an error message. The same command passes with `--verbose` or under Node 22.

## Backend, SDK and CLI tests (T002)

The T002 command runs the six files in one pytest session. That session stops before it runs any test, with `_pytest.pathlib.ImportPathMismatchError`, because `backend/tests/conftest.py` and `python_sdk/tests/conftest.py` both import as `tests.conftest`. CI runs the backend, SDK and CLI suites in separate pytest sessions ([ci.yml](../../.github/workflows/ci.yml)), so the baseline runs each file on its own.

| Test file | Passed | Failed | Pytest summary |
|-----------|--------|--------|----------------|
| `backend/tests/unit/repository/backup/test_backup_repository.py` | 7 | 0 | `7 passed in 0.61s` |
| `backend/tests/unit/services/backup/test_backup_service.py` | 33 | 0 | `33 passed in 0.11s` |
| `backend/tests/functional/graphql/test_backup_fields.py` | 5 | 0 | `5 passed in 0.74s` |
| `backend/tests/functional/graphql/test_backup_restore_steps_propagation.py` | 8 | 0 | `8 passed in 2.44s` |
| `python_sdk/tests/test_backups.py` | 17 | 0 | `17 passed in 0.04s` |
| `cli/tests/test_backups.py` | 30 | 0 | `30 passed in 0.41s` |

The four backend files in one session: `53 passed in 3.15s`.

## Frontend tests (T002)

The frontend tests need Node 22, and `pnpm install --ignore-workspace` must also run under Node 22. Under Node 18, pnpm skips the optional package `@rolldown/binding-linux-x64-gnu`, which requires Node `^20.19.0 || >=22.12.0`. Vitest then fails to start with `Cannot find native binding`.

- `pnpm test -- deployment-detail` does not apply the `deployment-detail` filter, so it runs the whole frontend suite: 84 files and 837 tests, all passing.
- `pnpm test deployment-detail` runs the 10 files in `frontend/src/__tests__/deployment-detail/`: 73 tests, all passing.

| Test file in `frontend/src/__tests__/deployment-detail/` | Passed | Failed |
|-----------------------------------------------------------|--------|--------|
| `BackupExpiry.test.tsx` | 7 | 0 |
| `BackupRestoreSteps.test.tsx` | 5 | 0 |
| `DeploymentDetailHeader.test.tsx` | 4 | 0 |
| `DeploymentTimelineSteps.test.tsx` | 9 | 0 |
| `DocumentTitle.test.tsx` | 3 | 0 |
| `StepList.test.tsx` | 16 | 0 |
| `StepListFailures.test.tsx` | 7 | 0 |
| `StepListLive.test.tsx` | 8 | 0 |
| `TaskResult.test.tsx` | 12 | 0 |
| `UpgradeDialogPinnedImages.test.tsx` | 2 | 0 |

## Failures before the change

None. No test in the files above fails at commit `1681b1ac`.
