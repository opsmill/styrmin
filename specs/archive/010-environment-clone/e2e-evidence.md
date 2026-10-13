# E2E Local-PASS Evidence — spec 010 (Environment Clone)

Constitution §V (NON-NEGOTIABLE) definition-of-done record for task **T043**.

**Status**: ✅ **Both dual-entrypoint variants PASSED locally on 2026-08-19.**

Test node: `test_environment_clone_lifecycle` in
`backend/tests/e2e/test_backup_restore.py` (`@pytest.mark.ci`, module shard
`shard_backup`). One heavy node deliberately covers US1–US4 (research D12,
"reuse before you boot").

---

## §V Evidence — `[api-chromium]`

| Item | Value |
|---|---|
| **pytest node ID** | `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]` |
| **Exact command** | `sleep infinity \| uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]" -v -s --pdb > /tmp/clone-e2e-api.log 2>&1` |
| **ISO 8601 timestamp (UTC)** | `2026-08-19T22:34:07+00:00` (PASS observed 22:34:03, vcluster teardown completed 22:34:07; run started 22:29:33) |
| **vcluster id** | `pytest-eb1dc5e9-5ffe-449b-be5c-69f6a8d2ba1f` (created 22:29:51, deleted by fixture teardown after the PASS) |
| **Kubeconfig path (during run)** | `/tmp/pytest-of-root/pytest-1379/vcluster0/kubeconfig` |
| **Verbatim `PASSED` line** | `PASSED22:34:03 info Removing vCluster container vcluster.cp.pytest-eb1dc5e9-5ffe-449b-be5c-69f6a8d2ba1f...` (pytest's `PASSED` and the teardown log share the line; ANSI colour codes stripped) |
| **Verbatim summary line** | `=================== 1 passed, 1 warning in 273.70s (0:04:33) ===================` |

## §V Evidence — `[ui-chromium]`

| Item | Value |
|---|---|
| **pytest node ID** | `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]` |
| **Exact command** | `sleep infinity \| uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]" -v -s --pdb > /tmp/clone-e2e-ui.log 2>&1` |
| **ISO 8601 timestamp (UTC)** | `2026-08-19T22:46:45+00:00` (PASS observed 22:46:42; run started 22:42:01) |
| **vcluster id** | `pytest-d6b421a4-ebb6-4a6e-868e-a870e70b6573` (created 22:42:21, deleted by fixture teardown after the PASS) |
| **Kubeconfig path (during run)** | `/tmp/pytest-of-root/pytest-1380/vcluster0/kubeconfig` |
| **Verbatim `PASSED` line** | `PASSED22:46:42 info Removing vCluster container vcluster.cp.pytest-d6b421a4-ebb6-4a6e-868e-a870e70b6573...` (ANSI colour codes stripped) |
| **Verbatim summary line** | `=================== 1 passed, 1 warning in 283.49s (0:04:43) ===================` |

The single warning in both runs is the unrelated
`kr8s/_vendored/asyncache` `DeprecationWarning` for
`asyncio.iscoroutinefunction`.

---

## What the passing runs prove

Asserted directly by the node, on both entrypoints:

- **SC-001** — one `cloneEnvironment` operation yields a counterpart
  deployment that reaches `running` in a brand-new environment, with zero
  per-deployment operator steps.
- **SC-002** — the source is untouched: config byte-identical either side of
  the clone, deployment roster unchanged, and the only source-side artefact
  gained is the one environment backup the clone was built from.
- **SC-003** — every source deployment considered is attributed exactly once
  (selected → `CLONED` with a counterpart and a restore; unselected →
  `SKIPPED` with a reason); internal deployments are omitted, which is what
  makes set *equality* the right assertion.
- **SC-004** — the clone holds the data as of the capture, not the source
  mutation written after it, proved by an **authenticated write** (`/count`)
  against the counterpart returning `200` and the capture-point counter.
- **SC-005** — deleting the created environment discards the clone, marks the
  record `discarded` with a `created_environment_deleted:` event, frees the
  name, and a second clone under that name is accepted and materialises.
- **FR-006** — the created environment's config is an exact-dict match for the
  captured config with `backup_ttl` cleared and the override merged over the
  rest.

## Residual-risk outcomes observed on the cluster

The task list carried six residual risks into this run. Observed:

1. **Flux install-vs-upgrade — did not bite.** The counterpart's HelmRelease is
   named for the *source's* release (`styrmin-<source_deployment_id>`) in the
   counterpart's namespace; helm-controller ran an `install` action over the
   Velero-restored release storage and it succeeded — the counterpart's
   `postgresql` and `simple-app` pods came up `1/1 Running`, and the
   authenticated write against the restored database returned `200` with the
   capture-point counter. Ownership validation did not reject it.
2. **Extra pod roll between Velero completing and the HelmRelease upsert** — not
   separately measured; the clone converged well inside
   `ENVIRONMENT_CLONE_TIMEOUT_SECONDS` either way.
3. **`execute_phase_helmrelease` writing HelmRepository/HelmChart into the
   `styrmin` namespace from the USER work pool** — no RBAC failure; the
   HelmRelease re-render succeeded and the counterpart reconciled.
4. **Counterparts left `RESTORING` with an active instance** so
   `target_instance_id` resolves — held; the `CLONED` attribution entry carried
   a non-null `restore_id`.
5. **USER flow deleting the target namespace before restoring** — benign as
   designed.
6. **UI selector drift** — none; every `data-testid` and the `Clones` tab label
   the page objects expect are present, and the `[ui-chromium]` variant drove
   the dialog (name, selection, override, clear-fields) and the clones section
   without a selector failure.

## Defect found and fixed to reach green

The first `[api-chromium]` run reached **step 10** with steps 1–9 all passing,
then failed on `deleteEnvironment` with `INTERNAL_ERROR`:

```
sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.IntegrityError:
<class 'asyncpg.exceptions.NotNullViolationError'>: null value in column
"environment_id" of relation "deployment" violates not-null constraint
```

Root cause — pre-existing on `develop`, not introduced by this feature:
`delete_environment` never cascaded the environment's **deployments**.
`deployment.environment_id` is non-nullable, so the ORM's reaction to the
deleted parent (null the child's FK) trips the constraint. Every existing
caller of `environments.delete` swallows the failure in a cleanup
`except`/`suppress`, so the gap had never surfaced — the clone's discard path
(SC-005) is the first place environment deletion is load-bearing, and a clone's
created environment *always* owns at least its counterparts plus an internal
ingress-controller deployment. The design assumed the cascade existed: the
derivation docstring already documents "a referenced id that is absent is a
restore that cascaded away".

Fix (same class and same remedy as the `environmentbackup` cascade added
earlier in this feature):

- `backend/styrmin_backend/repository/deployment.py` —
  `delete_all_for_environment`, hard-deleting an environment's deployments and
  their dependents in FK order (instances, components, deployed services,
  tasks, pod/CRD status, schedules, and their backups), breaking the
  `deployment.active_application_instance_id` cycle first and **detaching**
  rather than deleting cross-target restores so a clone's `restore_id` stays
  resolvable.
- `backend/styrmin_backend/services/deployment.py` —
  `request_cluster_teardown`, a best-effort `spec.deletionRequested` flip so the
  operator removes the Services, HelmRelease, NetworkPolicies/Secrets and the
  namespace; no state guard, because discard must work against `RESTORING`
  counterparts.
- `backend/styrmin_backend/services/environments.py` — `delete_environment`
  gains the teardown + cascade step between the environment-backup cascade and
  the environment row delete.
- `backend/tests/unit/services/fakes.py`,
  `backend/tests/unit/services/test_environment_services.py` — fake repository
  method and a unit test pinning the cascade and the per-deployment teardown
  request.

## Reproduce

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]" \
  -v -s --pdb 2>&1 | tee /tmp/clone-e2e-api.log

sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]" \
  -v -s --pdb 2>&1 | tee /tmp/clone-e2e-ui.log
```

Both variants are self-bootstrapping: the session-scoped `vcluster` fixture in
`backend/tests/conftest.py` creates a disposable vCluster on Docker and deletes
it on exit. Only `vcluster` and `docker` need to be on `PATH`.
