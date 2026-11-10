# Implementation report: service ingress override (#598)

Status: DONE. All 65 tasks of `tasks.md` are ticked and no row of the local-pass evidence is missing.

## 1. Header

| Item | Value |
|---|---|
| Feature | Service ingress override (issue #598), spec `033-service-ingress-override` |
| Spec directory | `/Users/Simon/styrmin-598-spec/specs/033-service-ingress-override` |
| Base commit | `5de4af5d` |
| Head commit before this report | `b0998a5a` |
| Commits produced | 47 (the report commit is the 48th), none pushed, all signed off, none with a co-author line |
| Size of the change | 136 files changed, 14,315 insertions, 330 deletions |
| Wall-clock time | about 8 hours 20 minutes (Overseer registration 2026-11-10T10:00Z, report written about 18:20Z) |
| Alembic revision | None needed. `git diff 5de4af5d -- backend/styrmin_backend/db/models.py backend/styrmin_backend/db/migrations` is empty. |
| Dependencies | None added. No manifest or lock file changed, so the dependency scan does not apply. |
| Orchestration | Each chunk ran in a clean-context subagent. The orchestrator wrote no feature code. |

The change makes Styrmin build the Ingress of every service that a driver declares `external`, and lets a team set the ingress class and the FQDN suffix of one service. The decision record is `dev/adr/0090-styrmin-builds-the-ingress-of-an-external-service.md`.

## 2. Chunk-by-chunk ledger

Outcome counts use the task outcomes of each chunk: done / partial / blocked. Chunks 15, 19 and 20 are not tasks of `tasks.md`: they fixed defects found during the run.

| # | Chunk | Tasks | Outcome | Commits | Decisions or surprises flagged by the subagent |
|---|---|---|---|---|---|
| 1 | Phase 1: verify the open points of the plan | 6 | 6 done | `fb5ef25e` | The `DeployedService` id is recreated on every services reconcile, so the Ingress is named after the driver service name (`styrmin-svc-<name>`). No `fqdn_suffix` validation existed to reuse. The contract was wrong about `services` in a manifest (a list of rows, not a map). The deploy form does not query `services`. |
| 2 | Phase 2: tests first | 5 | 5 done | `c3f2370c` | Tests for T007 to T010 fail for the planned symbol missing, as intended. T011 passes. |
| 3 | Phase 2: config, address function, builder | 6 | 6 done | `e41b5a8b` | Final names `compute_service_address` and `ServiceAddress`. The context entries gained keys `driver_service_name`, `scope`, `ingress_class`, `fqdn_suffix`. The order of the declared services is now deterministic. |
| 4 | Phase 2: operator support for Ingress | 4 | 4 done | `b5bf9399` | The operator manages only Ingresses with `managed-by=styrmin` and the release-reference label, so a chart's Ingress is never listed or deleted. |
| 5 | Phase 3: tests first | 4 | 4 done | `aeae249c` | The propagation test lives in `backend/tests/functional/graphql/`. The override test runs on the Infrahub Enterprise stack that has two active consumers. |
| 6 | Phase 3: builder override, API, regeneration, manifest | 5 + T030a | 6 done | `8223f731`, `cf276848`, `a99bd3c4` | Output field named `serviceIngressOverrides`. SDK `scale` cleared the stored `services`; fixed for `services` only. It also clears every other stored config key (not changed, see section 6). |
| 7 | Phase 3: Infrahub drivers | 2 | 2 done | `ad1e5673` | infrahub 5 to 6, infrahub-enterprise 4 to 5. A driver bump edits the example in place. |
| 8 | Phase 3: run the end-to-end test, API variant | 1 | 1 done | `55c002b3`, `7ebf1433` | Run 1 found a real defect: `apply_kubernetes_resource` had no `Ingress` branch (403). Run 2 found an empty release reference in an annotation. `sleep infinity` exits at once on macOS. |
| 9 | Phase 4: generic-app and read-only assertions | 5 | 5 done | `790198b9`, `ae9b1c02` | Only generic-app and the two Infrahub drivers declare an external service. T035 was already covered by T009. |
| 10 | Phase 5: UI tests first | 4 | 4 done | `8254138d` | 57 frontend tests fail for missing behaviour, as intended. |
| 11 | Phase 5: UI implementation | 5 | 5 done | `c8aa35b4` | Internal services are left out of the Networking summary. The UI save used to clear stored overrides; fixed in `deploymentConfigToInput`. |
| 12 | Suffix fix and UI end-to-end run | T048 + fix | done | `933ab8b0`, `7bcc9576`, `d77fec24` | The backend accepted `example.com\n` as a suffix; fixed with `re.fullmatch`. The first UI run failed because of a test bug, not a product defect. |
| 13 | Phase 6: validator and wiring | 4 | 4 done | `1b049fa3`, `b7f0c268` | The subagent handed back before committing; the orchestrator waited for the full run and had it commit. |
| 14 | Phase 6: UI errors, end-to-end run, class rule | 2 + fix | 2 done | `b55d24d2`, `f3f5668d`, `83874cce` | The override class is validated as a Kubernetes object name. One API run failed once with an empty release-reference label. |
| 15 | Investigation of the release-reference label | defect | fixed | `a0885121`, `4e676d69` | Two operator timers wrote the same Ingress with different release references. The label flipped every 2 to 25 seconds. The same flip also hit Service, Secret and NetworkPolicy. |
| 16 | Phase 7: user documentation | 4 | 4 done | `88c9c0c1`, `9bc812b8` | The wrong sentence that `apply` leaves omitted fields untouched was fixed in the CLI text. |
| 17 | Phase 7: ADR, knowledge pages, glossary, changelog | 3 | 3 done | `d962f8a3`, `a65a9329`, `772256e6` | ADR number is 0090 because 0089 exists on another branch. Two changelog fragments instead of one. |
| 18 | Phase 7: final checks | 4 | 3 done, 1 left open | `3c5fb844` | Stopped on a product defect (chunk 19). T065 was not ticked. |
| 19 | Fix of the missing Traefik label | defect + T065 | fixed, T065 done | `4b87a6f9`, `343e4072`, `6050cf69` | The Ingress that Styrmin built lacked the label `styrmin/environment_id`. A dedicated controller served HTTP 404 for it. The object-only tests could not catch this. Traffic checks were added. |
| 20 | Fixes of the review findings | 13 findings | all fixed | `ad2ed03d`, `7eb7434e`, `d0bb6e17`, `f03a0cea`, `7256c1a7`, `d9f4c8c0`, `3cdfe562`, `4ad7280e`, `029dafde`, `c01438b9`, `c3014f26`, `3923471c`, `b0998a5a` | See section 5. |

## 3. Tasks not completed

None. `grep -c '^- \[ \]' tasks.md` returns 0 and 65 tasks are ticked.

Not part of the 65 tasks, and left open on purpose, are the items in section 6 under "Open points".

## 4. Local-pass evidence

The run added or changed several hundred tests. The table lists one row per test file for unit, functional, SDK and frontend tests, and one row per test for end-to-end tests. The full list of test identifiers is in the files themselves. The verbatim end-to-end `PASSED` lines, the vCluster identifiers and the kubeconfig paths are in `specs/033-service-ingress-override/e2e-evidence.md`, section "Review fixes" (and the earlier sections for the history). The orchestrator re-ran the unit, functional, SDK and frontend commands after the last chunk and saw the pass lines in the table's last block.

Final-state runs by the orchestrator, 2026-11-10 after commit `b0998a5a` (environment: local macOS, no cluster):

| Test id | Type | Run command | Passed at (UTC) | Environment | Verbatim pass line |
|---|---|---|---|---|---|
| Backend unit tests matching `ingress or service_ingress or old_shape or apply_utility` (all new Ingress, validator, operator, label and apply tests) | unit | `uv run pytest backend/tests/unit -q -k 'ingress or service_ingress or old_shape or apply_utility' -p no:cacheprovider` | before 2026-11-10T18:18Z | n/a | `388 passed, 4824 deselected, 1 warning in 4.79s` |
| GraphQL functional tests matching `service_ingress or scale or manifest` | functional | `uv run pytest backend/tests/functional/graphql -q -k 'service_ingress or scale or manifest' -p no:cacheprovider` | before 2026-11-10T18:18Z | in-memory database | `59 passed, 666 deselected in 5.30s` |
| `python_sdk/tests` | unit | `uv run pytest python_sdk/tests -q` | before 2026-11-10T18:18Z | n/a | `384 passed in 0.59s` |
| Frontend (all files, including the new ones) | unit | `cd frontend && pnpm exec vitest run` | before 2026-11-10T18:18Z | n/a | `Test Files 105 passed (105)` and `Tests 1269 passed (1269)` |

Per-file evidence, taken from the subagent reports and checked again by the orchestrator where marked with an asterisk:

| Test id (file) | Type | Run command | Passed at (UTC) | Environment | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/unit/context/test_service_config_block.py` * | unit | `uv run pytest backend/tests/unit/context/test_service_config_block.py -q` | 2026-11-10T10:25Z (chunk 3), 18:18Z (final) | n/a | `40 passed` at chunk 3, `84 passed` after the class rule (chunk 14) |
| `backend/tests/unit/context/test_service_address.py` * | unit | `uv run pytest backend/tests/unit/context/test_service_address.py -q` | 2026-11-10T10:25Z | n/a | `16 passed in 0.13s` |
| `backend/tests/unit/agent/test_ingress_utility_service_ingress.py` * | unit | `uv run pytest backend/tests/unit/agent/test_ingress_utility_service_ingress.py -q` | 2026-11-10T10:25Z, 11:00Z | n/a | `32 passed in 0.13s`, later `96 passed in 0.36s` together with `test_utility_resources.py` |
| `backend/tests/unit/agent/test_utility_resources.py` (chart-patch regression T011, Prefect-path T021) * | unit | `uv run pytest backend/tests/unit/agent/test_utility_resources.py -q` | 2026-11-10T10:40Z | n/a | `191 passed in 0.68s` (six files together) |
| `backend/tests/unit/test_ingress_operator_reconcile.py` * | unit | `uv run pytest backend/tests/unit/test_ingress_operator_reconcile.py -q` | 2026-11-10T10:40Z | n/a | `191 passed in 0.68s` (six files together) |
| `backend/tests/unit/agent/test_infrahub_driver_task_manager.py` * | unit | `uv run pytest backend/tests/unit/agent/test_infrahub_driver_task_manager.py -q` | 2026-11-10T11:07Z | n/a | `18 passed in 0.10s` |
| `backend/tests/unit/services/service_ingress/test_validator.py` | unit | `uv run pytest backend/tests/unit/services/service_ingress/test_validator.py -q` | 2026-11-10T13:07Z | n/a | `37 passed in 0.04s` |
| `backend/tests/functional/graphql/test_service_ingress_propagation.py` (T023) | functional | `uv run pytest backend/tests/functional/graphql/test_service_ingress_propagation.py -q` | 2026-11-10T11:02Z | in-memory database | `19 passed in 1.74s` |
| `backend/tests/functional/graphql/test_service_ingress_validation.py` * | functional | `uv run pytest backend/tests/functional/graphql/test_service_ingress_validation.py -q -p no:cacheprovider` | 2026-11-10T13:07Z | in-memory database | `19 passed in 1.78s` |
| `backend/tests/functional/graphql/test_service_ingress_manifest_apply.py`, `test_sdk_scale_keeps_service_overrides.py` | functional | `uv run pytest <file> -q` | 2026-11-10T11:02Z | in-memory database | `3 passed in 0.46s`, `3 passed in 0.48s` |
| `backend/tests/unit/test_ingress_release_reference_label.py` * | unit | `uv run pytest backend/tests/unit/test_ingress_release_reference_label.py -q` | time not recorded (chunk 15, fix commit `a0885121`) | n/a | `9 passed` (7 of 9 fail without the fix) |
| `backend/tests/unit/agent/test_service_ingress_labels.py` | unit | `uv run pytest backend/tests/unit/agent/test_service_ingress_labels.py -q` | time not recorded (chunk 19, fix commit `4b87a6f9`) | n/a | `8 passed` (6 fail without the fix) |
| Frontend: `ServiceOverridesSection.test.tsx`, `NetworkingSummary.test.tsx`, `ConfigDiffDialog.test.tsx`, `config-diff.test.ts`, `config-impact.test.ts`, `deployment-input.test.ts`, `fqdn-suffix.test.ts`, `ingress-class.test.ts` | unit | `cd frontend && pnpm exec vitest run <files>` | 2026-11-10T12:27Z | n/a | `Test Files 7 passed (7)`, `Tests 229 passed (229)`; all files `1269 passed (1269)` at the end |
| SDK tests for apply and scale (`python_sdk/tests/test_deployments.py`) | unit | `uv run pytest python_sdk/tests/test_deployments.py -q` | 2026-11-10T11:02Z | n/a | `5 passed, 111 deselected` for the new cases; `384 passed` for the whole SDK at the end |
| Full backend suite | unit and functional | `uv run invoke test` | time not recorded (chunk 20, after commit `3923471c`) | local | `1 failed, 6131 passed, 8 skipped, 41 warnings in 365.91s`. The one failure is the known `services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused`. |

End-to-end tests, all on commit `3923471c8a5868d171cd7b12eeff73f6a59f2e3f` with an empty `git status` (the only file changed after it is the evidence file):

| Test id | Type | Run command | Started (UTC) | Environment | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/e2e/test_infrahub_services.py` (Traefik traffic check of the Prefect UI Ingress) | e2e | `sleep 86400 \| uv run pytest "backend/tests/e2e/test_infrahub_services.py" -v -s --pdb` | 2026-11-10T17:50:16Z | vCluster `pytest-b3710848-06fc-43a3-8dff-002acdbf5e1b`, `.../pytest-of-Simon/pytest-1484/vcluster0/kubeconfig` | `1 passed, 1 skipped, 4 warnings in 351.47s` |
| `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_moves_only_the_overridden_service[api-chromium]` (US1) | e2e | `sleep 86400 \| uv run pytest "<node>" -k api-chromium -v -s --pdb` | 2026-11-10T17:56:18Z | vCluster `pytest-d5325d9a-027b-43d8-88bc-10029855a443`, `pytest-1485` | `1 passed, 1 deselected, 4 warnings in 390.30s` |
| same test, `[ui-chromium]` (US1 and US3 through the UI) | e2e | same, `-k ui-chromium` | 2026-11-10T18:03:01Z | vCluster `pytest-a90d92a6-2d32-46e4-9b95-ca39a3283bed`, `pytest-1486` | `1 passed, 1 deselected, 4 warnings in 303.28s` |
| `backend/tests/e2e/test_service_ingress_override.py::test_service_ingress_override_refusals_name_the_service[api-chromium]` (US4) | e2e | `sleep 86400 \| uv run pytest "<node>" -k api-chromium -v -s --pdb` | 2026-11-10T18:08:13Z | vCluster `pytest-02b7e762-b0f9-4b05-b6f9-2377821decf0`, `pytest-1487` | `1 passed, 1 deselected, 4 warnings in 270.35s` |
| `backend/tests/e2e/test_deploy_generic_app.py::test_deploy_generic_app[api-chromium]` (US2) | e2e | same pattern, `-k api-chromium` | 2026-11-10T18:12:54Z | vCluster `pytest-ae3e2f62-a77c-4e78-b05f-5b3a7b852db8`, `pytest-1488` | `1 passed, 1 deselected, 4 warnings in 166.41s` |
| `backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium]` (SC-003 read-only assertion) | e2e | `sleep 86400 \| uv run pytest "<node>" ... --pdb` | 2026-11-10T12:05Z, on commit `790198b9`; not re-run after the review fixes | vCluster `pytest-c3d7beeb-b2c3-4e35-9497-865a0089af00`, `pytest-1420` | `2 passed, 6 warnings in 224.42s` (together with the generic-app test) |

The kubeconfig directory prefix for every row is `/private/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/`. The vCluster is removed at the end of each run, so the kubeconfig files no longer exist.

Notes on this evidence:

- The tests first written in a test-first chunk (for example T007 to T010) could not pass in that chunk. Their failing run was recorded then, and their passing run is in the rows above.
- Two e2e commands in earlier chunks used a throwaway plugin in the scratchpad that only prints `kubectl get ingress`. It changes no assertion.
- `test_deploy_simple_app` was not re-run after the review fixes, because the fixes do not touch a path that a driver without an external service uses. This is an inference, not a run.
- No local end-to-end limit applies: the e2e suite runs on a local vCluster. No row is `deferred`.

## 5. Review findings

The review (`speckit-review-run`) ran six reviewers in parallel, each in a clean context, on `git diff 5de4af5d..HEAD` (head `6050cf69`): code, tests, comments and documentation, errors, types, simplify. The simplify reviewer ran in report-only mode, so no unreviewed edit entered a 12,600-line change. The orchestrator fixed every finding of severity high and above, and the cheap medium findings that made a statement false or that guard a safety claim. The fixes were verified by the new tests, a full backend run, and five end-to-end runs on the final code.

Findings by reviewer and severity, as reported (some defects were reported by more than one reviewer):

| Reviewer | Critical | High | Medium | Low |
|---|---|---|---|---|
| code | 1 | 0 | 3 | 3 |
| tests | 0 | 0 | 8 | 3 |
| comments and documentation | 0 | 1 | 10 | 6 |
| errors | 1 | 4 | 4 | 3 |
| types | 0 | 1 | 5 | 4 |
| simplify | 0 | 0 | 5 | 8 |

Critical and high findings, and what happened to each:

| Severity | File | Summary | Decision |
|---|---|---|---|
| Critical (code), high (errors, types) | `agent/service/kubernetes/resources/utilities/ingress.py` | The builder read `service["scope"]` from `deployed_services`. A context stored before this release lacks the key, so the operator's drift timer raised `KeyError` and silently stopped correcting NetworkPolicy, Secret and Service. | Fixed in `ad2ed03d`. An old-shape entry is treated as not external. The timers now log the error with its traceback. |
| Critical (errors) | `agent/tasks/application.py` | `apply_utility_resources` swallowed every API error for an Ingress, so a refused Ingress left the deployment reporting success. | Fixed in `7eb7434e`. An Ingress apply error now raises. A custom kind is skipped only on 404. NetworkPolicy keeps its old behaviour and now logs status and reason. |
| High (errors) | `ingress.py` | A class-only override with no suffix anywhere silently built no Ingress. | Fixed in `ad2ed03d`. It now raises the same error as the chart patch, naming the deployment and the service. |
| High (errors) | `services/service_ingress/validator.py` | An override on an external tcp or udp service passed validation and built nothing. | Fixed in `d0bb6e17`. It is refused with `SERVICE_INGRESS_NOT_BUILT`, with the kind in the metadata. The UI offers the fields only for http and https services. |
| High (errors) | `python_sdk/.../deployments.py` | A mistyped key in a manifest `services` row (for example `fqdn_sufix`) was dropped, so `apply` succeeded and stored nothing. | Fixed in `f03a0cea`. The row is checked before it reaches the server. |
| High (comments and documentation) | `docs/docs/reference/styrmindeployment.md` | The page listed four Ingress labels, not the six the builder sets. | Fixed in `7256c1a7`. |

Medium findings fixed (all in chunk 20): the three different readings of a stored `services` value (one raised on `null`; now one helper), the two paths that applied an override to services of another scope, the Upgrade dialog message that told the user to act "in the same request", the untested registration of the Ingress drift handlers and the untested rule that a chart's Ingress is left alone (mutation checks showed both gaps), the end-to-end assertion that could not fail, the 404 claim for the overridden Ingress, the contradictions inside `e2e-evidence.md`, the changelog sentence that overstated the timer fix, the documentation statements without a source, and the missing terms in `CONTEXT.md`. A stored `"services": null` that made `deployedServices` return `INTERNAL_ERROR` was found during the fix and fixed too.

Findings recorded and left as they are (details in ADR-090, "Open points"):

- Medium, code: a class-only override on the first declared service removes the application address from its Ingress. This follows research decision D-003. The owner has to confirm it.
- Medium, code: the context reads every peer deployment through `uow.deployments.find` on each context generation. The cost was not measured.
- Medium, errors: a failed Ingress list returns no Ingress, so desired Ingresses are created again each cycle and stale ones are not deleted. The same pattern exists for the other kinds.
- Medium, errors: the Ingress drift handlers return without a log when the release-reference label is missing.
- Medium, types: the suffix and class rules exist in Python and TypeScript with no shared test cases. 21 edge cases were compared by hand and are equal.
- Low, code (not verified): with a dedicated controller and a default IngressClass on the cluster, the API server may add `spec.ingressClassName`, and the spec diff would then replace the Ingress on each pass.
- Low, errors: `_deployment_labels` drops a label with no value without a warning.
- Low and medium, simplify: unread `ingress_class` key in the context entries, a fallback that cannot run, leftover "planned symbol" comments in two test files, duplicated test fixtures, twin helpers in the frontend, three renames.
- Low, tests: no test shows that internal services are left out of the Networking summary, hard-coded fixture values in an end-to-end test, no test joins `compute_service_address` and the builder.
- GraphQL `DeployedService.ingressClass` still shows the resolved class for an external tcp service, although no Ingress exists.

## 6. Autonomous decisions

Decisions by the orchestrator or the subagents that the owner may want to revisit:

1. Commits. The user chose "blanket approval, local only" when asked at the start. Subagents committed each chunk with `git commit -s`, a Conventional Commit subject ending in `(#598)`, and no co-author line, which follows `~/.claude/CLAUDE.md` and overrides the attribution reminder of the session. Nothing was pushed.
2. Test-first commits are not green. Chunks 2, 5 and 10 committed tests that fail until the next chunk. The commits between those points are not individually green. If the pull request is not squashed, a bisect across them needs care.
3. Test-first chunks and the local-pass rule. T007 to T010 and the other test-first tasks could not pass in their chunk. The rule was applied as "fails for the right reason now, passes in the implementing chunk".
4. T005. The spec assumed an existing `fqdn_suffix` rule. None existed. A new validation was added for the override suffix (DNS name, at most 253 characters) and, later, a Kubernetes object-name rule for the override class.
5. Ingress name. It is `styrmin-svc-<driver service name>` and not built from the service id, because the id is recreated at every services reconcile. ADR-090 records this as an exception to the wording of ADR-073.
6. Output name. The stored overrides are exposed as `Deployment.serviceIngressOverrides`, not `services`, so they do not sit next to `deployedServices` under a similar name.
7. Both end-to-end variants. The override test runs as `[api-chromium]` and `[ui-chromium]` as `tasks.md` asks. The UI variant adds a second Infrahub Enterprise stack to CI (about five minutes locally). It can be limited.
8. Internal services are left out of the Networking summary. This narrows FR-016, which says "each service".
9. Two changelog fragments (`598.added.md`, `598.changed.md`) instead of one, because the breaking change for drivers that declare `external` has its own type.
10. ADR number 0090, because 0089 exists on `origin/032-styrmin-driver-cli`.
11. Operator timer fix (`a0885121`). The HelmRelease timer passed an empty release reference, so two timers overwrote each other's objects every few seconds. The fix applies to Ingress, Service, Secret and NetworkPolicy, not only to Ingress. This changes existing behaviour outside the feature. The flip was observed on `83874cce`. Whether it existed before this feature was not checked.
12. SDK `scale` (`a99bd3c4`). It now keeps `services`. It still clears every other stored config key, which is an existing defect. It was reproduced with a probe and left as it is.
13. Operator pipeline. `Ingress` was not added to the services phase of `operator/pipeline.py`. The Ingress is created by the HelmRelease timer pass: about one second after creation in the end-to-end setup (5-second timer), at most one timer interval in general (60 seconds by default, not measured).
14. `apply_utility_resources` now raises for an Ingress error. NetworkPolicy keeps its old behaviour of skipping any error.
15. The tcp and udp refusal reuses `SERVICE_INGRESS_NOT_BUILT` with the kind in the metadata, instead of a fourth code.
16. The review's simplify reviewer ran in report-only mode.
17. The AGENTS.md instruction to prefix end-to-end runs with `sleep infinity |` does not work on macOS (`sleep infinity` exits at once, so pdb quits and the vCluster is removed). Subagents used `sleep 86400 |`. AGENTS.md was not changed.
18. The first declared service when it is external but tcp or udp: no Ingress carries the application address. The spec is silent. The behaviour is pinned by a test, not changed.

Open points for the owner, not decided in this run:

- The PRD owner must confirm the changed FR-002 (critique E1) and decide the edge case about existing deployments whose driver declares `external` and renders its own Ingress (critique P1).
- Class-only override on the first service removes the application address (see section 5).
- The text "omitting a field leaves the persisted state untouched" on `UpdateDeploymentInput` (GraphQL description) and in ADR-018 is wrong. Changing the description needs regeneration and approval.
- Not verified in this work: traffic through an overridden Ingress, the Tailscale `tls` setting (no Tailscale operator or tailnet in the fixtures), the community `infrahub` driver upgrade (5 to 6), the 60-second default timer delay as a measured creation delay, backup and restore of an environment with Styrmin-built Ingresses, the number of drivers outside this repository, and a 404 from a live cluster for a missing Traefik custom resource (unit-tested only).
- Measured once on a local vCluster for the upgrade of Infrahub Enterprise from driver version 4 to 5: no request without HTTP 200 at the 5-second timer (2 runs), and 12 of 126 and 7 of 120 requests with HTTP 404 (about 12 and 7 seconds) at the 60-second timer (2 runs). These are samples, not guarantees.

## 7. Suggested next steps

1. Run the pull-request gates from `~/.claude/CLAUDE.md` in order, each in a separate agent that did not write the change: the `code-review` skill at level `high` on the PR diff, fix, then the `security-review` skill on the same change (check that `origin/HEAD` points at the PR's base branch). The Trivy scan does not apply, because no dependency was added. This run's six-reviewer pass is not the `code-review` or `security-review` skill and does not replace them.
2. Decide the open points of section 6, starting with FR-002 and the class-only override, and decide whether the timer fix (decision 11) goes into this pull request or its own.
3. Decide whether to squash, because of decision 2.
4. Decide whether to update AGENTS.md for macOS (decision 17).
5. Show the commit message, the file list and the review sections for approval before any push or pull request, as the global rules require.
