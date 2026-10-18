# Spike Notes: Recorded Demos of Four Styrmin Features

## Overview

Results of the checks of tasks T009 and T010 ([tasks.md](tasks.md)), run on 2026-10-18 on a fresh local demo stack. Each finding names the research item it confirms or changes.

- Infrahub 1.10.11 starts on chart 4.33.2 and upgrades to 1.11.7, so demo 1 keeps `previous: "1.10.11"` (research [R-015](research.md#r-015-infrahub-versions-for-demo-1)).
- On the demo stack, that upgrade does not run the `infrahub` driver's upgrade action, so Infrahub 1.11.7 runs on a database that `infrahub upgrade` has not migrated. Demo 1 waits for the fix to issue [#372](https://github.com/opsmill/styrmin/issues/372), as the maintainer decided on 2026-10-18. See "The upgrade does not run the driver's upgrade action".
- `infrahub-enterprise` 1.11.7 starts, and an environment backup and its restore both reach `COMPLETED` (research [R-007](research.md#r-007-environment-backups-need-the-infrahub-enterprise-driver)). Demos 3 and 4 can go on.
- One screencast records the whole run, including a navigation to a second origin, with the cursor still visible after it. The recorder does not need one recorded page per web application (research [R-001](research.md#r-001-playwright-version-and-the-screencast-api)).
- Demo 2 (`component-overrides`) records end to end on a fresh demo stack: a video of 0:45, and the whole command takes 8 min 15 s. Watching the first recordings showed that Playwright draws no highlight unless the recorder gives it a style, so the recorder now sets one (FR-004). See "Demo 2 recorded (tasks T035 and T036)".
- Demo 3 (`backup-restore`) records end to end on a fresh demo stack: a video of 1:06, and the whole command takes 13 min. After the restore, Infrahub lists `sw2` again and Semaphore lists the template "List network devices" again, so User Story 3's acceptance scenario passes. The `semaphore` driver backs up Semaphore's PostgreSQL database, and that is where the template is stored. See "Demo 3 recorded (tasks T037 and T038)".

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

## Semaphore reads the devices from Infrahub (tasks T023 to T026)

Checked on 2026-10-18 in the environment `spike-chunk7` on the demo stack, which was deleted afterwards. Semaphore was deployed with the parameter `docker_image=styrmin-demo/semaphore` and the driver's default version 2.16.47.

- The vCluster ran the image `styrmin-demo/semaphore:v2.16.47` that `docker build` had put on the host, with no other step. Task T030's `build_semaphore_image` only needs to run `docker build`.
- A deployment gets an alias Service only for the services of the deployments that exist when it is deployed. When `infrahub-enterprise` and `semaphore` were deployed at the same time, neither namespace had an alias Service, so `http://infrahub:8000` did not resolve in Semaphore. When Semaphore was deployed after Infrahub was running, its namespace had the aliases `infrahub` and `task-manager`. So the setups of demos 3 and 4 (tasks T037 and T039) deploy Infrahub, wait until it runs, and then deploy Semaphore. Not checked: whether a later change to the Infrahub deployment adds the missing alias.
- With the alias in place, the template "List network devices" printed `Devices in the inventory: 2` and `Device names: sw1, sw2` 1.5 s after the run started. Ansible also prints the warning `Found variable using reserved name: name`, because the inventory adds the attribute `name` as a host variable.
- Semaphore marks a task "Success" when the inventory cannot reach Infrahub: the play prints "skipping: no hosts matched". A demo checks the device count in the output, not only the task status.
- The Infrahub device list can show its footer ("2 counts") a moment before it shows the rows, so `InfrahubDevicesPage.goto` waits until the number of rows equals the count.
- Times: deploying `infrahub-enterprise` 91 s, then `semaphore` 91 s; `semaphore_setup.configure` under 1 s; deleting the environment 51 s.

## Demo 2 recorded (tasks T035 and T036)

Recorded on 2026-10-18 with `uv run invoke record --demo component-overrides` on a demo stack that `uv run invoke reset` had just created (12:24:37 to 12:26:37 UTC). The run lasted from 12:26:59 to 12:35:14 UTC and printed one `recorded` line.

The video `demo-videos/2-component-overrides.mp4`:

- `ffprobe` gives `h264,1920,1080,yuv420p` at 30 frames per second and a length of 44.9 s, which the summary shows as 0:45.
- It shows the two chapter titles, the cursor and a blue outline on each element the script clicks or types into, the image reference typed one key at a time, and each wait sped up with its label.
- It ends on the Component Overrides card of the Infrahub deployment with `server` `replicas 2 (override)` and the badge "applied". The step before shows the Semaphore card with `image styrmin-demo/semaphore:v2.16.47` and "applied".
- No password, token or login form is on screen.

Checked with `kubectl` while the run was in its second step, before the cleanup deleted the environment:

- The Semaphore pod ran `styrmin-demo/semaphore:v2.16.47` (`kubectl get pod -n styrmin-<semaphore id> -o jsonpath='{.items[*].spec.containers[*].image}'` printed `bitnamilegacy/postgresql:17.6.0-debian-12-r4 styrmin-demo/semaphore:v2.16.47`). Before the override, the Semaphore pod of the setup ran `semaphoreui/semaphore:v2.16.47`.
- The Infrahub server Deployment had `replicas=2` and two ready pods once the second wait ended.

After the run, only the `local` environment existed, and no `styrmin-<deployment id>` namespace was left.

### Real duration of each wait

| Wait | Fresh stack (the recorded run) | Earlier trial runs |
| --- | --- | --- |
| "Semaphore restarts with the new image" | 51 s, shown 13 times faster | 53 s and 51 s |
| "A second Infrahub server starts" | 1 min 13 s, shown 19 times faster | 1 min 35 s and 1 min 13 s |

`DeploymentDetailPage.wait_for_new_task` ran against a real browser for the first time in these runs. Each time it returned when the timeline showed the `update_instance` task as succeeded.

### What changed after watching the first recordings

- Playwright 1.64 draws a highlight only when `show_actions` gets a `style.highlight`, and its action title shows the Playwright locator, for example `Click locator("[data-testid=section-nav-componentOverrides]")`. The recorder now passes a highlight style (a blue outline) and hides the title with `display: none`, as the Playwright reference for screencasts suggests. The cursor stays. Each action now stays on screen for 800 ms instead of 500 ms, so a viewer can follow the clicks. This applies to every demo.
- The first recording opened the Timeline tab at the start of each step to read the task ids, and the next action reloaded the page at once. The setup now reads the task ids of both deployments before the recording starts.
- The first recording ended on the timeline, which shows the succeeded task but not the result of the override. After each wait, the demo now holds 1.5 s on the succeeded task, then opens the Settings tab, scrolls the component's row of the Component Overrides card into view (new page-object method `DeploymentDetailPage.show_component_overrides`) and holds 3 s. The demo fails unless the row shows the image reference or `2 (override)`.
- The demo opens the Timeline tab before each wait starts, so the click on the tab plays at normal speed.

Not changed: the mouse stays where the last click was, so after the page scrolls it rests on an unrelated element (the Infrahub service link in the last frame). The video is 45 s long and has no dead time longer than the 3 s holds.

## Demo 3 recorded (tasks T037 and T038)

Recorded on 2026-10-18 with `uv run invoke record --demo backup-restore` on a demo stack that `uv run invoke reset` had just created (13:01:54 to 13:04:06 UTC). The run lasted from 13:04:27 to 13:17:27 UTC and printed one `recorded` line.

Before writing the scenario, the `semaphore` driver was read: its `database` component has `backup: {enabled: true, kind: postgres, database_name: semaphore}` ([`driver/examples/semaphore/driver.styrmin.yml`](../../driver/examples/semaphore/driver.styrmin.yml)). The template is stored in that database. The PostgreSQL restore hook runs `pg_restore --clean --if-exists --single-transaction` ([`velero/hooks.py`](../../backend/styrmin_backend/agent/service/kubernetes/velero/hooks.py)), so the restore brings back the template the demo deletes. No driver change was needed.

The video `demo-videos/3-backup-restore.mp4`:

- `ffprobe` gives `h264,1920,1080,yuv420p` at 30 frames per second and a length of 66.2 s, which the summary shows as 1:06.
- Each of the five steps starts with its chapter title.
- The cursor and the blue outline are on each element the demo clicks: the Backups tab, "Create Backup", the row menu of `sw2` and "Delete" in Infrahub, the template link, the delete icon and "Yes" in Semaphore, "Restore" and the "Restore" button of the confirmation dialog. Demo 3 types into no text field during the recording, because both logins happen during the setup.
- The three long waits are sped up with their labels: "Sped up 16×: Backup in progress took 1 min", "Sped up 43×: Restore in progress took 2 min 48 s" and "Sped up 5×: Infrahub restarts took 18 s".
- Infrahub lists `sw1` and `sw2`, then only `sw1` with the message "Object sw2 deleted", and after the restore `sw1` and `sw2` with "2 counts". Semaphore lists "List network devices", then no template with the message `Template "List network devices" deleted`, and after the restore the template again.
- No password, token or login page is on screen. The Semaphore template list shows the name of the variable group, "Infrahub token", but not its value; the variable group page is never opened.

After the run, only the `local` environment existed, and no `styrmin-<deployment id>` namespace was left.

The Infrahub and Semaphore sessions of the setup still worked after the restore, so the last step needs no new login. Both logins happen before the backup, so the restored databases still hold them.

### Real duration of each wait

| Wait | Fresh stack (the recorded run) | Earlier trial runs on a kept environment |
| --- | --- | --- |
| "Backup in progress" | 1 min, shown 16 times faster | 48 s and 39 s |
| "Restore in progress" | 2 min 48 s, shown 43 times faster | 1 min 9 s and 5 min 19 s |
| "Infrahub restarts" | 18 s, shown 5 times faster | 27 s and 3 s |
| "Semaphore restarts" | 0 s, not sped up | 0 s and 0 s |

The restore recreates the pods of both deployments. When the recorded restore completed, the Semaphore pods were 2 min 11 s old and had not restarted, and the Infrahub pods were 32 s old; the Infrahub server and task-manager pods had each restarted twice before Infrahub answered. The duration of the restore varied between 1 min 9 s and 5 min 19 s over three runs; the cause of the variation was not investigated. Another session's E2E vCluster was running on the host when the trial runs started and was gone before the recorded run.

### What changed after the first trial runs

- The first trial stopped in the setup: Chromium could not resolve `infrahub-network-lab-backup.local.styrmin.io` (`net::ERR_NAME_NOT_RESOLVED`), although the Infrahub SDK had just reached the same address and the same name resolved a minute later. `resolvectl statistics` reported one timeout and one failure response. The recorder's browser now maps `*.local.styrmin.io` to `127.0.0.1` with `--host-resolver-rules`, which is the address the wildcard DNS record gives ([local demo guide](../../dev/guides/local-demo.md)). This applies to every demo.
- The first recording opened each Semaphore page from its address, so the video showed three white pages while Semaphore loaded. The demo now clicks the template in the list (new page-object method `SemaphoreTemplatesPage.open_template`) and reads the list that Semaphore opens after the deletion (new method `listed_template_names`, which first waits for the list address, because a template's own page also holds a table, of its tasks). Only the switch from Infrahub to Semaphore still shows a white page.
- The Semaphore wait (new helper `semaphore_setup.wait_until_ready`, which polls `GET /api/ping`) took 0 s in all three runs, so it never shows a label. It stays, so that a Semaphore restart after a restore cannot make the last step fail.

