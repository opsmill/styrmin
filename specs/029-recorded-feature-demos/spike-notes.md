# Spike Notes: Recorded Demos of Four Styrmin Features

## Overview

Results of the checks of tasks T009 and T010 ([tasks.md](tasks.md)), run on 2026-10-18 on a fresh local demo stack. Each finding names the research item it confirms or changes.

- Infrahub 1.10.11 starts on chart 4.33.2 and upgrades to 1.11.7, so demo 1 keeps `previous: "1.10.11"` (research [R-015](research.md#r-015-infrahub-versions-for-demo-1)).
- On the demo stack, that upgrade does not run the `infrahub` driver's upgrade action, so Infrahub 1.11.7 runs on a database that `infrahub upgrade` has not migrated. Demo 1 waits for the fix to issue [#372](https://github.com/opsmill/styrmin/issues/372), as the maintainer decided on 2026-10-18. See "The upgrade does not run the driver's upgrade action".
- `infrahub-enterprise` 1.11.7 starts, and an environment backup and its restore both reach `COMPLETED` (research [R-007](research.md#r-007-environment-backups-need-the-infrahub-enterprise-driver)). Demos 3 and 4 can go on.
- One screencast records the whole run, including a navigation to a second origin, with the cursor still visible after it. The recorder does not need one recorded page per web application (research [R-001](research.md#r-001-playwright-version-and-the-screencast-api)).

The throwaway scripts that ran the checks stayed in the session scratchpad and are not committed.

## Demo stack used for the checks

- Image: `registry.opsmill.io/opsmill/styrmin:latest`, rebuilt with `uv run invoke build` from this branch (commit `60d82a86`) before the stack started. The image that had the `latest` tag before was built on 2026-10-11 from another branch.
- The first `uv run invoke reset` stopped at its first step: `vcluster delete styrmin` failed with "vCluster container vcluster.cp.styrmin not found", although the vCluster's Docker volumes still existed. `uv run invoke start` then reused those volumes, so the stack held namespaces created 176 days earlier and nearly 2,000 old pods. A second `uv run invoke reset`, run once the container existed, deleted the vCluster and created a fresh one. That reset took 2 min 9 s (10:18:53 to 10:21:02 UTC).
- Credentials: the admin user from `dev/local/demo-values.yaml`.

## Infrahub 1.10.11 starts on chart 4.33.2 and upgrades to 1.11.7

Environment `spike-upgrade` on cluster `local`, deployment `infrahub` of the `infrahub` driver (driver version 5, chart 4.33.2):

1. Deploying `infrahub` at 1.10.11 reached Running 136 s after the request. The `create_instance` task's step "Install or upgrade the HelmRelease" took 120 s of that time. The Infrahub API was not queried while the deployment ran 1.10.11.
2. `client.deployments.update_version(deployment_id, "1.11.7")` started an `upgrade_instance` task. The task succeeded and the deployment was Running at 1.11.7 61 s after the request. Its step "Install or upgrade the HelmRelease" took 37 s.
3. After the upgrade, every pod was ready, the server, task-worker and task-manager pods ran `registry.opsmill.io/opsmill/infrahub:1.11.7`, `GET /api/info` returned `"version":"1.11.7"`, and the Infrahub home page loaded in the browser (T010 below).

Demo 1 keeps `previous: "1.10.11"` and `latest: "1.11.7"`; the fallback to an older 1.11 release is not needed.

## The upgrade does not run the driver's upgrade action

The `infrahub` driver declares an `upgrade` action (`hook: upgrade`, `mode: core`) that stops the server and task workers, runs `infrahub upgrade` in a job, and starts them again ([`driver/examples/infrahub/actions.py`](../../driver/examples/infrahub/actions.py)). On the demo stack this action did not run:

- The `upgrade_instance` task had these six steps and no other: "Plan the changes", "Write the StyrminDeployment resource", "Create network policies and secrets", "Install or upgrade the HelmRelease", "Create services and middlewares", "Wait for the deployment to be ready". No step started another task.
- The task worker logged, verbatim:

  ```text
  INFO | styrmin_backend.services.reconciliation.remediation:_handle_upgrade:249 - No upgrade core hook defined for application=infrahub, will use regular update
  ```

- The upgraded Infrahub server logged, verbatim:

  ```text
  warning  ] Expected database graph version 79 but got 75, possibly 'infrahub upgrade' has not been executed
  ```

Cause, from the code: Styrmin registers a driver's action workflows only when the driver is loaded from a Git source ([`backend/styrmin_backend/services/applications.py`](../../backend/styrmin_backend/services/applications.py), comment "Register token and action workflows only for git-sourced drivers"). `uv run invoke start` loads `infrahub` and `semaphore` from local paths (`/styrmin/drivers/<name>`), and demos 3 and 4 load `infrahub-enterprise` the same way. Without a registered upgrade action, the reconciliation falls back to a plain HelmRelease upgrade ([`remediation.py`](../../backend/styrmin_backend/services/reconciliation/remediation.py), `_handle_upgrade`).

Effect on the plan:

- Demo 1 step 3 (task T033) expects "the expanded task and its steps, including the driver's upgrade action". On the demo stack the timeline shows the six steps above and no upgrade action.
- Research R-015 says the upgrade from 1.10 to 1.11 "runs the driver's upgrade action with Infrahub's migrations, which is what demo 1 shows". On the demo stack it does not, and Infrahub runs on graph version 75 instead of 79.

How to resolve it is not decided. The code offers one route without a product change: load the driver from a Git source, which registers its actions. The demo stack has no Git server today, and whether the recorder may reach a remote repository is not known. The other route is a product change so that locally loaded drivers register their actions. The code gap is already filed as [#372](https://github.com/opsmill/styrmin/issues/372), "actions of drivers loaded from a local directory are never registered and never run".

Decision (maintainer, 2026-10-18): demo 1 (tasks T033 and T034) waits for the fix to #372. Loading the driver from a Git server inside the demo stack, and recording the upgrade without the action, were both rejected. Task T032 (the versions file) still lands, because demos 2 and 3 deploy the `latest` version.

## infrahub-enterprise 1.11.7 backs up and restores

Environment `spike-backup` on cluster `local`, with the stack's backup storage location `local` assigned (`client.backup_storage_locations.list()` returned one location, then `assign`):

1. `client.drivers.load_local_version("/styrmin/drivers/infrahub-enterprise")` loaded driver version 4 (chart 4.19.2) at once.
2. Deploying `infrahub-enterprise` at 1.11.7, named `infrahub`, reached Running 142 s after the request. The pods ran `registry.opsmill.io/opsmill/infrahub-enterprise:1.11.7` and `neo4j:2026.05.0-enterprise`, and `GET /api/info` returned `"version":"1.11.7"`.
3. `client.environment_backups.create` took a backup with one constituent, `infrahub`. It reached `COMPLETED` 52 s after the request; the constituent backup ran for 40 s of that time.
4. `client.environment_backups.restore` skipped no constituent and reached `COMPLETED` 135 s after the request; the constituent restore ran for 120 s of that time.
5. The deployment was Running as soon as the restore completed, but Infrahub answered `GET /api/schema/summary` with 503 until about 36 s later (200 at 10:35:33, restore completed at 10:34:57). The server and task-manager pods had each restarted twice. Demo 3's wait "Infrahub restarts" around `infrahub_setup.wait_until_ready` (task T037) is needed.

Not checked: whether data written before the backup comes back after the restore. The spike wrote no data. Demo 3 checks it with the device and the template.

## Service URLs of the deployments

Each deployment exposed two services, both `http` with scope `internal`. `service_url(deployment, service_name)` (task T021) reads `humanReadableUrl`, which has the form `http://<service>-<environment>.local.styrmin.io:8080`.

| Deployment | Service | Port | Component | `humanReadableUrl` |
| --- | --- | --- | --- | --- |
| `infrahub` in `spike-upgrade` | `infrahub` | 8000 | `server` | `http://infrahub-spike-upgrade.local.styrmin.io:8080` |
| `infrahub` in `spike-upgrade` | `task-manager` | 4200 | `task-manager` | `http://task-manager-spike-upgrade.local.styrmin.io:8080` |
| `infrahub` (`infrahub-enterprise`) in `spike-backup` | `infrahub` | 8000 | `server` | `http://infrahub-spike-backup.local.styrmin.io:8080` |
| `infrahub` (`infrahub-enterprise`) in `spike-backup` | `task-manager` | 4200 | `task-manager` | `http://task-manager-spike-backup.local.styrmin.io:8080` |

Observed, not investigated: the `primaryUrl` of the `task-manager` service was the same as the `primaryUrl` of the `infrahub` service (`http://infrahub-<deployment id>.local.styrmin.io:8080`, or `http://infrahub-enterprise-<deployment id>...` for the enterprise driver). The demos do not use `primaryUrl`.

## Time each operation took

Wall-clock times from the request to the state named, measured by the spike scripts. They set the expected length of each sped-up wait and of a full run (research [R-017](research.md#r-017-how-long-a-full-run-takes)).

- Fresh demo stack with `uv run invoke reset`: 2 min 9 s.
- Deploy `infrahub` 1.10.11 to Running: 136 s.
- Upgrade to 1.11.7 until the task succeeded and the deployment was Running: 61 s, without the driver's upgrade action. With the action, the upgrade also stops and starts components and runs `infrahub upgrade`, so it would take longer; how much longer is not measured.
- Deploy `infrahub-enterprise` 1.11.7 to Running: 142 s.
- Environment backup to `COMPLETED`: 52 s.
- Environment restore to `COMPLETED`: 135 s, then about 36 s until Infrahub answered.
- Delete an environment with one Infrahub deployment until its namespace was gone: 170 s (`spike-upgrade`) and 224 s (`spike-backup`). The 600 s timeout of `stack.delete_environments` (task T021) covers both.

## One screencast records both origins

The script opened a 1920×1080 page in headless Chromium (Playwright 1.64.0) on the Styrmin login page and then:

1. `page.screencast.start(path=..., size={"width": 1920, "height": 1080})`, which returned after 2 ms;
2. `show_actions(cursor="pointer", position="top")`;
3. `show_chapter("Test", duration=1500)`;
4. a click on the Styrmin username field;
5. `page.goto("http://infrahub-spike-upgrade.local.styrmin.io:8080")`, another origin, while the `spike-upgrade` deployment still ran;
6. a click on the first link of the Infrahub page (the Infrahub logo), then a 2 s pause;
7. `stop()`, which returned after 0.11 s.

Results:

- The raw file is WebM with VP9, 1920×1080, `yuv420p`, at a constant 25 frames per second (`r_frame_rate` and `avg_frame_rate` `25/1`): 166 frames from 0.00 s to 6.60 s.
- It lasts 6.64 s, and the run from `start()` returning to `stop()` returning took 6.77 s. The file covers the whole run, including the part after the navigation.
- `show_chapter` blocks: with `duration=1500` the call returned after 1.82 s, its duration plus about 300 ms. A chapter of `duration=2500` (task T020) adds about 2.8 s to the video, as research R-001 says.
- A click with `show_actions` took about 0.55 s, because the annotation holds each action for 500 ms by default.

What the frames show:

- At 0.8 s: the Styrmin login page, blurred, with the chapter title "Test" on a dark rounded card in the middle.
- At 2.3 s: the Styrmin login page with the pointer on the username field and the annotation `Click locator("#login-username")` at the top.
- At 3.2 s: Infrahub's "Loading schemas..." screen, with the pointer still visible at the place of the previous click. The pointer survives the navigation to the other origin.
- At 4.6 s: the Infrahub home page (branch `main`, "Open Proposed changes", "Tasks overview"), with the pointer on the Infrahub logo and the annotation `Click get_by_role("link").first` at the top.
- Last frame: the same Infrahub home page with the pointer on the logo and no annotation.

Consequence: the recorder keeps one recorded page for Styrmin, Infrahub and Semaphore. The R-001 fallback (one recorded page per web application, joined afterwards) is not needed, and task T019 stays as written.

The action annotation shows the Playwright locator expression, for example `Click locator("#login-username")`. The audience reads it in the video. `show_actions` accepts `font_size` and `style` options; whether the annotation text can be hidden while keeping the pointer was not checked. Task T020 may need to decide whether to keep the annotation.

## Other observations for later tasks

- Calling `client.drivers.load_local_version("/styrmin/drivers/infrahub-enterprise")` again on a stack that has the version returned the same driver version id and raised no error. `stack.load_enterprise_driver` (task T021) does not need to catch an error for an already-loaded version.
- The `infrahub-enterprise` driver stays loaded on the demo stack after the spike. Only the `local` environment is left, and no `styrmin-<deployment id>` namespace remains.
- The SDK methods that task T009 names exist with these names: `client.deployments.update_version`, `client.backup_storage_locations.list` and `assign`, `client.environment_backups.create`, `wait_for_backup`, `restore` and `wait_for_restore`.
