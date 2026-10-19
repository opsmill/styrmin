# PR Notes: A Clone Writes Its Own Service Aliases and Restores None of the Source's (#530)

## The defect, the fix, and the open decisions

After an environment clone, each counterpart's namespace held the source's service aliases, so an application in the clone that called a peer by its short service name reached a deployment of the source environment ([#530](https://github.com/opsmill/styrmin/issues/530)). With this change:

- a cross-target restore restores no service alias;
- after its recovery, a cross-target restore writes the new environment's aliases in the step "Create and delete service aliases";
- a failed alias write fails the restore, and a clone entry whose restore failed reads `failed` with the restore's error;
- in-place and environment restores do not change.

Not decided yet: the autonomous answers in the spec and the description-only change of `schema.graphql`, listed below for the maintainer to confirm.

## Test results: both E2E variants passed

- [e2e-evidence.md](e2e-evidence.md) records both E2E sessions of `test_environment_clone_lifecycle` and `test_environment_backup_and_restore_lifecycle`: `api-chromium` (`2 passed, 2 deselected`, after a test fix in `73d9d4bf`) and `ui-chromium` (`2 passed, 2 deselected`). It also holds the quickstart walk-through (T037) and the observer reads of the Velero Restores and alias Services.
- After the review, both variants ran again at the final head `ffbcf1b1` and passed: `api-chromium` and `ui-chromium`, each `2 passed, 2 deselected` ([e2e-evidence.md](e2e-evidence.md), "Re-run at the final head").
- The quickstart's unit and functional tests: `268 passed` (e2e-evidence.md, T037).
- The backend suite outside E2E: `5194 passed, 3 skipped` (message of commit `1d9f7ce3`).

## High-risk files and what changed in each

- `backend/styrmin_backend/workflows/templates/backup.py`: for a cross-target restore, the INTERNAL flow passes the counterpart's `GlobalContext` to the USER flow as the new parameter `counterpart_context`, and the USER flow runs the alias step after "Run the recovery"; a failed alias step stores `recovered: False` with the error, which fails the restore.
- `backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py`: `build_velero_restore` gives a cross-target restore the label selector `styrmin.io/service-alias NotIn ["true"]`, and an in-place restore none.
- `backend/styrmin_backend/agent/service/kubernetes/velero/resources.py`: `VeleroRestore` gets the optional field `label_selector`, written to `spec.labelSelector` only when set.
- `backend/styrmin_backend/agent/tasks/service_aliases.py`: holds `apply_service_aliases_step`, moved from `orchestration.py` with the same body.
- `backend/styrmin_backend/agent/tasks/orchestration.py`: the create, update and upgrade flows call the moved step; the private copy and the unused import of `with_current_peer_services` are removed.

The selector depends on Velero 1.18.1 checking `spec.labelSelector` only on the items it reads from the backup. `dev/knowledge/backend/orchestration-flows.md` records the Velero source lines, so that a review of a Velero upgrade checks them.

## Autonomous answers for the maintainer to confirm

The spec flags these answers, which the PRD did not give. Each one can be confirmed or rejected on its own ([spec.md, Clarifications](spec.md#clarifications)):

- Reuse of the alias step of #503: "Yes. The cross-target restore runs the same step "Create and delete service aliases" as the create, update and upgrade flows. That step reads the other deployments' services from the server when it runs, so the counterpart whose restore ends last writes the aliases in both directions between it and each counterpart whose restore ended before."
- The namespace rule in FR-002 and SC-001: "No. A counterpart whose namespace is missing or terminating when another counterpart's alias step runs gets its aliases from its own alias step, at the end of its own restore, or from its next create, update or upgrade flow. [...] SC-001 counts only deployments whose namespace exists when the clone ends."
- FR-007 for every cause of a failed restore: "The clone record reports the entry of a counterpart whose restore failed as `failed`, with the restore's error as the reason. This applies to any failed counterpart restore, because an alias write failure is reported as a restore failure." The critique session kept it: "Yes, for one rule across causes. It stays flagged for the maintainer (critique P1)."
- The counterpart's status after an alias failure: "The restore still sets the counterpart to `FAILED`, as any failed restore does, and its status then follows its workloads." So a counterpart whose alias step failed can read `RUNNING` a few seconds later; the failed restore and the clone entry keep the failure.
- The `CONTEXT.md` entry "Service alias": "The fix extends that entry with what a clone does with aliases."

## Description-only change of `schema.graphql`, for the maintainer to confirm

- The diff adds sentences to the descriptions of the type `EnvironmentCloneDeploymentResult` and its fields `outcome` and `reason`. No type, field, argument or enum value changes. `frontend/src/generated/graphql.ts` changes the same comments.
- The spec treats this as no GraphQL schema change for the "Ask first" list of `AGENTS.md`, because FR-007 changes only what `outcome` and `reason` return for an entry whose restore failed.
- The type's description said that `counterpartDeploymentId` is "null unless CLONED", but the clone flow also stores the ids on a `FAILED` entry. After the review, it says that the id is null when the clone created no counterpart deployment for the source deployment. The added sentence says that an entry whose restore failed reads `FAILED`, with the reason `the restore failed: <the restore's error>`, or `the restore failed` when the restore has no error message, and keeps its `counterpartDeploymentId` and `restoreId`.

## A fix to the SC-001 check and a limit of the SC-003 check

- Commit `73d9d4bf`: the first `api-chromium` session failed in the SC-001 check, because the `deployment` query returns null for an internal deployment, such as the new environment's `styrmin-ingress-controller`. The check now reads the new environment's services with the `environmentServices` query, which also lists internal deployments. Source: [e2e-evidence.md](e2e-evidence.md), "First attempt", and the commit message.
- The SC-003 check in `test_environment_backup_and_restore_lifecycle` cannot tell whether Velero restored the alias or the second deployment's update flow rewrote it, because the environment restore also redeploys the second deployment. Source: the report of the implementation step that wrote the check (T025, commit `28b1bfc8`).

## Changes made after the review, including one to the create, update and upgrade flows

The review of the whole change ([opsmill-implement-report.md](opsmill-implement-report.md)) added three commits after `3a3c6982`:

- `f7bb114f`: the alias step lists the aliases in the cluster before it opens. When that list failed in a clone's restore, the restore failed, but no step held the error, which FR-004 and SC-004 require. The step now records an error raised before it opens as the failed step "Create and delete service aliases". A failed read of the environment's services from the server still does not fail the step, which then uses the services that the context lists (#503).
  - The create, update and upgrade flows call the same step, so in those flows too a failed read is now recorded as the failed alias step. Before, those flows failed with no alias step recorded.
  - Both E2E variants ran again at `ffbcf1b1`, which holds this commit, and passed ([e2e-evidence.md](e2e-evidence.md), "Re-run at the final head").
- `8da6967e` and `e52c8600`: documentation that the change had made false, the description of `counterpartDeploymentId` above, and `CONTEXT.md`, which said that a restore has at most three steps.

## Effect on the demo branch `fac/demo-beta-presentation-bhshh`

This change carries the alias check of commit `472fe403` (FR-016 of [#518](https://github.com/opsmill/styrmin/issues/518)), extended for SC-001 of this spec. That commit is on `fac/demo-beta-presentation-bhshh` only, so the demo branch drops it when it is rebased onto a `develop` that holds this change.

## Commits

`git log --oneline f816ac25..405813a7`, newest first. The commit that adds this file follows `405813a7`.

```text
405813a7 test(e2e): record the ui-chromium run for #530
b364b819 test(e2e): record the api-chromium run for #530
73d9d4bf fix(e2e): read the clone's services with environmentServices (#530)
1d9f7ce3 chore(specs): record the #530 checks
93f757b2 docs: explain how a clone writes its service aliases (#530)
28b1bfc8 test(e2e): check that an environment restore keeps its service aliases (#530)
362ede28 fix(api): report a clone entry whose restore failed as failed (#530)
693f73f6 fix(backup): fail the restore when its service aliases cannot be written (#530)
c3726101 test(e2e): check that a partial clone reaches no source deployment (#530)
57ddcec4 test(e2e): check that a clone's counterparts hold the clone's aliases (#530)
084be5ce fix(backup): write the clone's service aliases after its recovery (#530)
7ee6cb7f fix(backup): restore no service alias in a cross-target restore (#530)
82af8343 refactor(agent): move the service alias step out of orchestration (#530)
202c091a chore(specs): record the #530 baseline
```
