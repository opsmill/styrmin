# Follow-up Issues of Spec 029: Actions of Driver Versions Loaded from a Local Directory

**Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md) | **Evidence**: [e2e-evidence.md](e2e-evidence.md) | **Issue**: [#372](https://github.com/opsmill/styrmin/issues/372)

Each third-level heading below is the title of one issue for the maintainer to open, and the text under it is the issue's body. No issue was opened from this file.

The issues come from three sources:

- the follow-ups that [research.md](research.md#follow-ups-to-open-after-this-change-ships) lists;
- the findings made while the feature was implemented that this branch does not fix;
- the run of the quickstart on the dev stack (task T050, recorded in [e2e-evidence.md](e2e-evidence.md#t050-the-quickstart-sections)).

## Follow-ups that research lists

### Prefect: report why a flow run could not load its flow

This issue is for the Prefect project (PrefectHQ/prefect). It also covers the finding that a failed pull step writes nothing to the flow run's logs, because both are the same gap: Prefect does not report why a flow run could not load its flow, and Styrmin works around both in the same place.

What is wrong, under Prefect 3.8.6:

- When a flow run cannot load its flow, for example because a pull step raised or `actions.py` failed to import, the flow run ends `Crashed` with the state message `Process exited with status code: 1. …`. The message does not hold the exception text ([research R-002](research.md#r-002-how-the-error-of-the-check-reaches-the-hook-step)).
- A pull step that raises writes nothing to the flow run's logs. Prefect prints the traceback to the process output only. Research R-002 expected `load_flow_from_flow_run` to log the error in the flow run; the first E2E run of T028 showed that it does not for pull steps ([e2e-evidence.md](e2e-evidence.md#what-the-earlier-runs-of-t028-found)).

Effect: without the Styrmin workarounds, the hook step of a local driver check that fails would show only the exit status. The driver author would not see the path, the image and the provenance fingerprints that the error names.

Workarounds in Styrmin, which can be removed once every place that runs actions uses a Prefect release with the fix:

- `check_local_driver` logs its error at `ERROR` in the flow run before it raises ([`workflows/local_driver.py`](../../backend/styrmin_backend/workflows/local_driver.py)).
- `run_deployment_or_fail` reads the first `ERROR` log of a crashed flow run and adds it to the error of the hook step ([`agent/tasks/utils.py`](../../backend/styrmin_backend/agent/tasks/utils.py)).

Proposed change in Prefect: when a flow cannot be loaded, put the exception text in the `Crashed` state message, and log the error of a failed pull step in the flow run's logs.

### Run the actions of a driver that is mounted only into the server

What is missing: the actions of a driver version loaded from a local directory run from the driver version's path in the agent pod. A driver that exists only in the server, for example one copied into the server pod or mounted only into it, fails each hook with `DriverFilesNotFoundError`. A shared driver volume was out of scope of this change ([spec.md](spec.md), "Decisions and Rejected Alternatives": "A Helm value that mounts a shared driver volume into the server and into action Jobs was rejected for this change and becomes a follow-up issue").

The spec and research describe the volume as mounted into action Jobs. The actions run as processes in the agent pod (see "Decide what the `image:` of an action does" below), so such a volume would have to be mounted into the agent pod, which the [`helm/agent`](../../helm/agent) chart installs, and into the server.

Effect: an operator who adds a driver to a running installation without building a new image can load it, but its actions fail. Only drivers that are at the same path in the agent pod's image run their actions ([`loading-drivers.md`](../../docs/docs/drivers/loading-drivers.md)).

### Run the `pre` and `post` actions of the `upgrade` hook when a driver version declares no `upgrade`/`core` action

What is wrong: `resolve_upgrade_hooks` returns no hooks when the target driver version declares no action for the `upgrade` hook in the `core` mode. The change then runs as an update, and the actions declared for `upgrade`/`pre` and `upgrade`/`post` do not run. This rule existed before this change and was kept ([research R-007 and R-012](research.md#r-012-driver-versions-that-declare-upgradepre-or-upgradepost-without-upgradecore)). No driver in this repository declares this combination.

Effect: a driver author who declares only `upgrade`/`pre` or `upgrade`/`post` actions finds them registered in Prefect, but they never run, and no step or error says so.

Code: [`services/driver/hooks.py`](../../backend/styrmin_backend/services/driver/hooks.py) (`resolve_upgrade_hooks`).

### Let a user run an upgrade again after its action failed

What is wrong: after an upgrade whose action failed, the new instance stays the active instance of the deployment. A second request for the same application version is a no-op (`_update_is_noop`), and a request for another driver version at the same application version runs as an update, which runs no hook ([research R-009](research.md#r-009-running-the-same-upgrade-again-after-it-failed-for-a-missing-registration-fr-007), critique P5). This change avoids the problem only for a missing registration, which `update_deployment_version` detects before it writes anything. An action that fails while it runs is not covered.

Effect: to run the failed upgrade again, the operator has to request another application version first, or delete the deployment and create it again. The quickstart run of T050 met this case: after the `simple-app` upgrade action failed at `0.1.0`, only a request for `0.2.0` ran the upgrade action again ([e2e-evidence.md](e2e-evidence.md#scenario-a-version-without-registrations-user-story-3)).

Code: [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py) (`_update_is_noop`, `update_deployment_version`). Spec: "Edge Cases" and "Out of Scope".

### Comment on #10: driver versions loaded from a local directory now register their actions without git

This is a comment to add to [#10](https://github.com/opsmill/styrmin/issues/10) ("refactor: Remove Git dependency from base Prefect workflows and workflow manager"), not a new issue.

#10 says that user actions still need `GitSourceWorkflowDefinition` "unless user actions are also migrated to local sources". Since #372, `ActionsWorkflowBuilder` registers the actions of a driver version loaded from a local directory with `LocalDriverActionWorkflowDefinition`. Their Prefect deployment has one pull step, `check_local_driver`, which checks the files at the driver version's path and needs no git clone and no GitHub token ([`services/user.py`](../../backend/styrmin_backend/services/user.py), [`workflows/models.py`](../../backend/styrmin_backend/workflows/models.py), [ADR-081](../../dev/adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md)). The actions of a driver version loaded from git still use `GitSourceWorkflowDefinition` and the token block, so #10 still has to keep that path for them.

## Follow-ups from findings made during the implementation

### Decide what the `image:` of an action does

What is wrong: a driver can set `image:` on an action, and Styrmin passes it to the action's Prefect deployment as `job_variables["image"]` (`WorkflowDefinition.to_deployment` in [`workflows/models.py`](../../backend/styrmin_backend/workflows/models.py)). The agent runs every action with a Prefect `ProcessWorker` on the work pool `user-work-pool`, as a process in the agent pod ([`entrypoint/combined.py`](../../backend/styrmin_backend/entrypoint/combined.py)). So `image:` has no effect. The first E2E run of T028 showed it: an action whose `image:` held the driver failed with "The driver files are not at … in the image …", because the action ran in the agent pod ([e2e-evidence.md](e2e-evidence.md#what-the-earlier-runs-of-t028-found)). The errors of the local driver check still name an image: the action's `image:` or the default image of the work pool. That text was kept on purpose.

Effect: a driver author who sets `image:` expects the action to run in that image with its packages. The action runs in the agent pod with the agent's packages instead, and a failed check names an image that did not run the action.

Options, not decided:

- Run actions in their image, for example with a work pool whose worker creates a Kubernetes Job for each flow run, for the actions that set `image:` or for all actions. The image would then need the driver at the driver version's path, and the image that the check names would again be the image that ran the action.
- Remove the field: refuse `image:` when a driver is loaded, with a note for the drivers that set it.
- Deprecate the field: keep accepting it, show a load warning that says it has no effect, and remove it in a later release.
- Keep the field, document that it has no effect, and change the error text to name the agent pod.

### Delete the empty namespace of a create whose `StyrminDeployment` write failed

What is wrong: since T052 (commit `1f97d5b2`), `deleteDeployment` deletes a deployment whose create failed before its `StyrminDeployment` was written: it sets the deployment to `deleting`, and the status reporter tombstones it. The create flow writes the namespace and then the `StyrminDeployment` in one step (`_write_styrmin_deployment` in `create_instance_crd`). When the namespace was created and the `StyrminDeployment` write then failed, the delete finds no `StyrminDeployment` and leaves the namespace in the cluster. This case has no test.

Effect: after the deployment is deleted, an empty namespace named after the deployment's id stays in the cluster until someone deletes it by hand.

Code: [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py) (`delete_deployment`), [`agent/tasks/orchestration.py`](../../backend/styrmin_backend/agent/tasks/orchestration.py) (`create_instance_crd`). Task: T052 in [tasks.md](tasks.md).

### Give a local driver version loaded from a relative path its own action registrations

What is wrong: the key under which the actions of a driver version are registered and looked up holds no source type. Its `directory/` tag holds the driver directory of a git driver version and the path of a local driver version as it was given on the server (`action_directory_of` in [`services/driver/labels.py`](../../backend/styrmin_backend/services/driver/labels.py)). A git driver directory never starts with `/`, because `normalise_driver_directory` refuses it. A local path starts with `/` only when it was given as an absolute path: the CLI (`styrminctl drivers load-local-version`), the SDK (`load_local_version`), the GraphQL mutation `loadLocalApplicationDriverVersion` and `LocalDriverProvider` ([`services/driver/provider.py`](../../backend/styrmin_backend/services/driver/provider.py)) pass the path on as given. `LocalDriverProvider` checks only that the path exists and is a folder, relative to the working directory of the server process.

A local driver version loaded from a relative path, such as `drivers/my-app`, therefore gets the same tags, and for an action of the same name the same Prefect deployment name, as a git driver version of the same driver and supported versions loaded from the driver directory `drivers/my-app`, when the first 7 characters of its `content_hash` equal those of the git commit SHA. By chance, two 7-character fingerprints are equal for about 1 in 268 million pairs.

Effect, read from the code and not tested:

- When the two keys are equal, `ensure_action_registrations` finds the flows of the driver version loaded first and registers nothing for the second one, so the hooks of the second driver version run the actions of the first one. When the git driver version was loaded first, the local driver version runs the git code, and the check of its own files does not run.
- Without an equal key, the check of a local action resolves a relative path against the working directory of the flow run's process, which is a temporary folder that the agent's `ProcessWorker` creates. The actions of a local driver version loaded from a relative path are therefore expected to fail with `DriverFilesNotFoundError`.

These texts say that a local value always starts with `/` and must be corrected with the fix: [research R-003](research.md#r-003-registration-key-of-a-local-driver-versions-actions) ("A `directory/` value of a local version starts with `/` and a git value never does, so the two cannot match").

Options, not decided:

- Refuse a relative path when a driver is loaded from a local directory.
- Make the path absolute on the server when a driver is loaded. The stored `source_path` then differs from the path that the user gave.
- Add the source type to the registration key, as a tag and in the deployment name. Registrations made before the change would then need to be found without that tag.

### Reconcile the spec, research and contracts of 029 with actions that run in the agent pod

What is wrong: these texts describe a local action as a Kubernetes Job that runs in the action's `image:`, or in the default image of the work pool, and checks the driver files in that image. The actions run as processes in the agent pod (see "Decide what the `image:` of an action does").

- [spec.md](spec.md): the summary; the clarifications on the image the error names and on checking the image at load; user story 1 and its scenario 4 ("its Job runs in that image"); user story 2 and its scenarios 1 and 3; the edge case of an `image:` that does not hold the driver; FR-002, FR-003 and FR-004; the entry "Provenance fingerprint" under key entities; assumptions A-1 and A-2; the "Out of Scope" item on running an upgrade again; the "Decisions and Rejected Alternatives" on where the Job reads the driver.
- [research.md](research.md): R-001 (the `image:` reaches the Job), R-004 (the environment of the action's Job), R-006 (the image that the error names), R-011 (the derived image proves that the action ran in its `image:`), R-013 (what a custom action image must hold).
- [contracts/local-driver-check.md](contracts/local-driver-check.md): the title and the resolution of the image named in the errors. [contracts/errors.md](contracts/errors.md): "Words that name the image of the action's Job".
- [quickstart.md](quickstart.md): section 2 (the derived image, and `kubectl get jobs` to inspect actions) and the section 3 scenario "An edited action without an image rebuild", which fails only when the files in the agent pod differ from the files the server loaded.

Effect: a reader of the spec expects behaviour that the code does not have. The error text keeps naming an image, as decided; the reconciliation should state which image that is and that it does not run the action.

Evidence: [e2e-evidence.md](e2e-evidence.md#what-the-earlier-runs-of-t028-found) and the list of differences in [e2e-evidence.md](e2e-evidence.md#differences-between-the-quickstart-or-the-spec-and-the-observed-behaviour).

## Follow-ups from the quickstart run on the dev stack (T050)

These problems are not caused by this change, and this branch does not change the code involved. They are recorded here because the quickstart run met them ([e2e-evidence.md](e2e-evidence.md#t050-the-quickstart-sections)).

### Let a driver action call `execute_commands` more than once on the same deployment

What is wrong: `execute_commands` creates a Job named `<release reference>-job`, with no `ttlSecondsAfterFinished`, and does not delete it after it completes ([`actions/primitives.py`](../../backend/styrmin_backend/actions/primitives.py)). The next `execute_commands` on the same deployment fails while that Job exists: `run_job` raises "Job … already exists in namespace …", with the exception class `CustomResourceNotFound`, which names a different problem ([`agent/service/kubernetes/primitives.py`](../../backend/styrmin_backend/agent/service/kubernetes/primitives.py)).

Effect: the second upgrade of a `simple-app` deployment failed in its upgrade action. The action had already stopped the `server` component and changed the version, so the deployment showed `running` at the new version with no server pod. The upgrade actions of `simple-app` and `infrahub` call `execute_commands`, so the second upgrade of any deployment of these drivers fails the same way until someone deletes the Job.

### Let the agent of the dev stack reach the Styrmin API on Linux

What is wrong: [`docker-compose.yml`](../../docker-compose.yml) sets `STYRMIN_URL_API_K8S=http://host.docker.internal:8000` on the server, and the server writes it as `STYRMIN_URL_API` into the environment of the work pool `user-work-pool` ([`workflows/catalogue.py`](../../backend/styrmin_backend/workflows/catalogue.py)). The agent container uses the host network, and on a Linux host `host.docker.internal` does not resolve there.

Effect: on a Linux dev stack, the flows and actions that the agent runs cannot reach the Styrmin API. No step is recorded (the agent logs `Could not record STARTED for step hook:setup:pre: [Errno -2] Name or service not known`), so a task shows only "Plan the changes" and its result can read `SUCCEEDED` while the deployment failed. Action primitives that call the API fail. The T050 run worked around it by adding `127.0.0.1 host.docker.internal` to `/etc/hosts` in the agent container.

### Give the cluster of the dev stack the Traefik resources that deployments need

What is wrong: `uv run invoke dev.bootstrap` creates the cluster record without `dedicated_ingress`, and the dev cluster has no Traefik, so it has no Traefik CRDs. The services phase of every deployment with an HTTP service then fails with `Failed to apply Middleware/auth: (404)`, and the task fails at "Create services and middlewares". Only the demo flow runs `cluster.traefik` ([`tasks/dev.py`](../../tasks/dev.py), [`tasks/cluster.py`](../../tasks/cluster.py)). The E2E session creates its cluster with `dedicated_ingress`.

Effect: on a dev stack brought up with `uv run invoke dev` or the `dev-validate` skill, a deployment of `semaphore` or `simple-app` fails until the developer installs Traefik.

### Delete a deployment on the dev stack

What is wrong: `deleteDeployment` patches the `StyrminDeployment` from the server (`_patch_deletion_requested` in [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py)). The server container of the dev stack has no Kubernetes configuration, so the call fails with "An internal error occurred", and the server logs `Failed to load in-cluster Kubernetes config`.

Effect: on the dev stack, a developer cannot delete a deployment. A failed deployment keeps its service names, so the next create of the same driver in that environment fails with "Service name … already exists in environment".

### Make the bundled `simple-app` driver deployable when it is loaded from `/styrmin/drivers/simple-app`

What is wrong: the chart location of `driver/examples/simple-app` is `simple-app`, with no repository. Only the E2E session rewrites it to the URL of its chart server ([`backend/tests/e2e/conftest.py`](../../backend/tests/e2e/conftest.py)). Loaded from `/styrmin/drivers/simple-app`, the driver is accepted, and the create fails at the HelmRelease phase: `HelmRepository.source.toolkit.fluxcd.io "…" is invalid: spec.url: Required value`.

Effect: the driver that the quickstart uses for its `simple-app` scenarios cannot be deployed on the dev stack as it is, and the load gives no warning.

Options, not decided: give the bundled driver a chart location that the dev cluster can fetch; refuse, or warn about, a chart location without a repository when a driver is loaded; or document that the bundled `simple-app` driver is for the E2E suite only.
