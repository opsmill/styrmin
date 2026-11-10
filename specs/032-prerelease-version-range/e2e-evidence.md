# E2E evidence: prerelease application versions

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Quickstart**: [quickstart.md](quickstart.md), step 3

This file records the evidence that constitution principle V requires: the end-to-end node `test_deploy_prerelease_simple_app` passed in both entrypoint variants. Every value below is quoted from a pytest log or from a file on this Mac. Where a log lacks a field, the entry says "not in the log".

Log directory: the scratchpad log directory (not committed)

Link between the runs and the committed code, not verified: the last commit that changes `backend/tests/e2e/test_deploy_app.py` is `7b3bef02` (author time 2026-11-10 11:08:49 +0100). It adds the step that requests `1.0.0b1` with and without a pin. The two passing runs below ended at 11:02 and 11:07 local time, before that commit time. The logs do not contain the test source, so they do not prove that the working-tree file at run time was the same as the committed file. The orchestrating session reports that the working tree was not changed between the end of the runs and the commit `7b3bef02`: it checked `git status` and the diff after the runs and committed exactly the files that the run had used. The commit is dated after the runs because the user approves each commit after the work is done. This is an observation of the orchestrating session, not something the logs prove. `git diff 7b3bef02 HEAD` for `backend/tests/e2e/test_deploy_app.py` and for `backend/styrmin_backend` is empty (checked 2026-11-10). The later changes to the E2E directory (task T028) are the deletion of `backend/tests/e2e/test_prerelease_version.py` and of the helper `publish_simple_app_driver_build`, which this node does not use.

## Passing run, variant `[api-chromium]`

| Field | Value |
| --- | --- |
| Pytest node id | `backend/tests/e2e/test_deploy_app.py::test_deploy_prerelease_simple_app[api-chromium]` |
| Log file | `e2e_api.log` |
| Exact command | Not in the log. The log header shows `collected 12 items / 11 deselected / 1 selected`, which matches a `-k prerelease` selection. The command that quickstart step 3 prescribes is `sleep infinity \| uv run pytest backend/tests/e2e/test_deploy_app.py -k prerelease -v -s --pdb`. The log does not prove that this exact line was typed. |
| Time of the passing run | The log has no date. The `PASSED` line carries the clock time `11:02:13` (local time, CET, UTC+1 on this Mac). The file `e2e_api_start.txt` holds `2026-11-10T09:57:02Z`. With that offset, the `PASSED` line is at 2026-11-10T10:02:13Z (derived, not in the log). The modification time of `e2e_api.log` is Nov 10 11:02:18 2026 local (file metadata). |
| Cluster identifier (vcluster) | `pytest-74c59121-a85a-4dab-8265-b9f0e800d6c2` (from the log lines `Successfully created virtual cluster pytest-74c59121-a85a-4dab-8265-b9f0e800d6c2` and `Successfully deleted virtual cluster ...`) |
| Kubeconfig path | Not in the log. Fixture directories have the form `/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-<user>/pytest-N/vcluster0/kubeconfig`. The directory of this run no longer exists (checked: no remaining `vcluster0/kubeconfig` names `74c59121`), so the path is not verified. |
| Verbatim `PASSED` line | `PASSED` followed on the same line by the vcluster log text: `PASSED 11:02:13 info Removing vCluster container vcluster.cp.pytest-74c59121-a85a-4dab-8265-b9f0e800d6c2...` (log line 640; the escape codes of the colours are left out) |
| Final summary line | `=========== 1 passed, 11 deselected, 4 warnings in 313.40s (0:05:13) ===========` (log line 656) |

## Passing run, variant `[ui-chromium]`

| Field | Value |
| --- | --- |
| Pytest node id | `backend/tests/e2e/test_deploy_app.py::test_deploy_prerelease_simple_app[ui-chromium]` |
| Log file | `e2e_ui.log` |
| Exact command | Not in the log. Same selection header (`collected 12 items / 11 deselected / 1 selected`). Same prescribed command as above; not proven by the log. |
| Time of the passing run | The log has no date. The `PASSED` line carries the clock time `11:07:31` (local, CET). The file `e2e_ui_start.txt` holds `2026-11-10T10:02:27Z`; the first log line of the vcluster is at `11:02:30`, so the offset is the same one hour. The `PASSED` line is therefore at 2026-11-10T10:07:31Z (derived, not in the log). The modification time of `e2e_ui.log` is Nov 10 11:07:36 2026 local (file metadata). |
| Cluster identifier (vcluster) | `pytest-bd2fd0ad-c909-4b21-92ab-941e5462d72a` |
| Kubeconfig path | `/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-<user>/pytest-1387/vcluster0/kubeconfig`. This path is not in the log. It was found on disk: the file exists and its cluster, context and user names contain `pytest-bd2fd0ad-c909-4b21-92ab-941e5462d72a`. |
| Verbatim `PASSED` line | `PASSED 11:07:31 info Removing vCluster container vcluster.cp.pytest-bd2fd0ad-c909-4b21-92ab-941e5462d72a...` (log line 464; colour codes left out) |
| Final summary line | `=========== 1 passed, 11 deselected, 4 warnings in 307.14s (0:05:07) ===========` (log line 480) |

## History, not the evidence

These runs happened earlier in the work. They are listed so that the sequence is clear. None of them is the evidence above.

| Log file | What the log shows |
| --- | --- |
| `e2e-prerelease.log` | First run of both variants together, started `2026-11-10T09:00:45Z` (file `start.txt`). The `[api-chromium]` variant reached `PASSED` (line 1770). The `[ui-chromium]` variant ended in ERROR before the prerelease steps: `UI timeout while creating cluster 'test-cluster': Locator.click: Timeout 30000ms exceeded.` while waiting for the button "New Cluster". Summary: `1 passed, 10 deselected, 4 warnings, 1 error in 350.83s (0:05:50)`. The log ends with `Quitting debugger`. |
| `e2e-prerelease-ui.log` | `[ui-chromium]` alone, started `2026-11-10T09:07:17Z`. It failed at the Deploy form: `deploy form rejected the deployment: Deployment failed` / `Version 0.2.0-beta.1 is not supported by driver version 22db5022-d01a-4da2-b621-557f53525c70 (supports >=0.1,<1.0).` The server log in the same file has `InvalidVersionError` and `code=VALIDATION_ERROR` for the same text. This was the first run, before the check of a pinned version was changed (the change is in the code of the run of `e2e-prerelease-ui2.log`; the log itself does not name a commit). Summary: `1 failed, 11 deselected, 4 warnings in 205.85s (0:03:25)`. |
| `e2e-prerelease-ui2.log` | `[ui-chromium]` after the pin check was changed, started `2026-11-10T09:11:00Z`. Summary: `1 passed, 11 deselected, 4 warnings in 249.66s (0:04:09)`. |
| `e2e-prerelease-api.log` | `[api-chromium]` after the same change, started `2026-11-10T09:15:29Z`. Summary: `1 passed, 11 deselected, 4 warnings in 217.84s (0:03:37)`. |
| `e2e-api.log` | `[api-chromium]` in the run of an earlier chunk, started `2026-11-10T09:22:32Z`, ended `2026-11-10T09:27:56Z` (files `api.start`, `api.end`). Summary: `1 passed, 11 deselected, 4 warnings in 320.68s (0:05:20)`. The log was not overwritten. |
| `e2e-ui.log` | `[ui-chromium]` in the run of the same chunk, started `2026-11-10T09:28:05Z`, ended `2026-11-10T09:33:43Z` (files `ui.start`, `ui.end`). Summary: `1 passed, 11 deselected, 4 warnings in 334.44s (0:05:34)`. The log was not overwritten. |

The two logs `e2e_api.log` and `e2e_ui.log` (with an underscore) are the later runs and are the evidence recorded at the top of this file.

## Not verified

- The exact command line of any run: no log contains it.
- The kubeconfig path of the `[api-chromium]` run.
- Any run after the deletion of `backend/tests/e2e/test_prerelease_version.py`: no E2E test was run for that deletion. The test collection (`uv run pytest backend/tests/e2e --collect-only -q`) listed 225 tests without error.
