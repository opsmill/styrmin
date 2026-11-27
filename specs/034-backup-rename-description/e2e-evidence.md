# E2E evidence: backup rename and description (#39)

This file records the E2E runs required by constitution §V for task T040.

## Environment

- macOS (arm64), Docker Desktop 29.2.0, vcluster 0.38.0.
- `COMPOSE_PARALLEL_LIMIT=1` was exported for every run. Without it, the
  `docker compose build` step in the `styrmin_deployment` fixture fails on
  this machine with `image "registry.opsmill.io/opsmill/styrmin:latest":
  already exists`. The `server`, `task-worker` and `agent-operator` services
  build the same image tag in parallel, and the Docker Desktop image store
  rejects the second write of that tag. With the limit set to 1, the services
  build one at a time and the build succeeds. This is not caused by this
  feature.
- `uv run playwright install chromium` was run before the UI-variant run,
  because the installed Playwright version needed the
  `chromium_headless_shell-1248` browser.
- `[api-chromium]` and `[ui-chromium]` ran in two separate pytest sessions to
  keep peak memory lower. Each session created its own vcluster.

## Run 1: `[api-chromium]` variant

- Node id: `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium]`
- Command:

  ```bash
  export COMPOSE_PARALLEL_LIMIT=1
  sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle" -v -s --pdb 2>&1 | tee e2e3.log
  ```

- Timestamp of the pass: 2026-11-27T16:17:53Z. The log lines in this run had
  no timestamps. This is the time of the vcluster teardown line that the log
  printed a few seconds after the `PASSED` line. The session started at
  16:06:13Z.
- vcluster: `pytest-793eafe7-bba2-47e8-a102-d1b73b37ed28`
- Kubeconfig: `/private/var/folders/jy/js48plld5p5_6jmmnm0q6ts40000gn/T/pytest-of-alex/pytest-104/vcluster0/kubeconfig`
- `PASSED` line (the test id and `PASSED` are printed on separate lines,
  because `-s` lets the fixture output appear between them):

  ```text
  backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium] ...
  PASSED
  ```

- The `[ui-chromium]` variant in the same session failed in fixture setup.
  Playwright could not start, because the
  `chromium_headless_shell-1248` executable was not installed. The test
  itself did not run. Run 2 repeats it after the browser was installed.

## Run 2: `[ui-chromium]` variants

- Node ids:
  - `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]`
  - `backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium]`
    (uses the shared `create_backup` page object)
- Command:

  ```bash
  export COMPOSE_PARALLEL_LIMIT=1
  sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]" "backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium]" -v -s --pdb 2>&1 | <prefix each line with the UTC time> > e2e4.log
  ```

- Session start: 2026-11-27T16:18:43Z
- vcluster: `pytest-531bdced-c0ca-4eb3-89a1-eff07146c331`
- Kubeconfig: `/private/var/folders/jy/js48plld5p5_6jmmnm0q6ts40000gn/T/pytest-of-alex/pytest-105/vcluster0/kubeconfig`
- `test_backup_and_restore_lifecycle[ui-chromium]` passed at
  2026-11-27T16:28:58Z. The log line, with the time prefix added by the
  command:

  ```text
  16:28:58 PASSED
  ```

- `test_restore_lifecycle_transitions[ui-chromium]` passed at
  2026-11-27T16:30:51Z. The log line:

  ```text
  16:30:51 backend/tests/e2e/test_backup_restore.py::test_restore_lifecycle_transitions[ui-chromium] PASSED
  ```

- Session summary:

  ```text
  16:31:00 ================== 2 passed, 5 warnings in 734.27s (0:12:14) ===================
  ```
