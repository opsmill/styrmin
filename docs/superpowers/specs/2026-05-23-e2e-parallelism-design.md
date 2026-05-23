# E2E Test Parallelism & Execution Speedup — Design

**Tracking issue:** [opsmill/styrmin#242](https://github.com/opsmill/styrmin/issues/242)
**Date:** 2026-05-23
**Status:** Design approved; pending implementation plan via `writing-plans`.

## Problem

`backend/tests/e2e/` (22 test files, ~5,800 LOC) is the largest contributor to
CI wall-clock. The suite is split into two CI jobs — `e2e-tests-api` and
`e2e-tests-ui` — each booting one vcluster, running every collected test
serially in a single worker, ~20 min apiece per AGENTS.md.

The shape is conservative: nearly every fixture in
`backend/tests/e2e/conftest.py` is `scope="session"` (vcluster, chart_server,
git_server, styrmin_deployment, styrmin_resources, deployed_simple_app,
deployed_infrahub_app, deployed_semaphore, deployed_db_test), and the
dual-entrypoint parameterization (`driver_mode = api|ui`) is also
session-scoped — but the actual *workload* is serialized inside one worker per
job. `pytest-xdist` is a declared dependency, unused for E2E.

Issue #242 targets a **30%+ wall-clock reduction on the slower job** while
preserving the dual-entrypoint contract (`api_only` / `ui_only` markers),
the `--pdb` debugging workflow (AGENTS.md), and zero loss of coverage.

## Approach

Four phases, each delivering a measurable wall-clock win independently so the
work can stop after any phase if the numbers are good enough. The unifying
principle: **the cost in CI is dominated by N × (vcluster_boot +
helm_install + image_builds), and the win comes from either reducing N or
amortizing the constant**.

| Phase | Risk | Effort | Expected win on slower job |
|---|---|---|---|
| 1 — Baseline + marker hygiene | Low | ~1 day | 15–30% (UI job only) |
| 2 — Tiering + UI smoke merge + sharing policy | Low–Med | ~1–2 days | ~5% direct; unblocks Phase 3 |
| 3 — Matrix sharding × 6 shards × 2 entrypoints | Med–High | ~3–5 days incl. tuning | 35–55% — the headline win |
| 4 — Docs + ADR + guardrails | Low | ~1 day | 0% direct; prevents regression |

**Combined target: 50–65% reduction on the slower job, well above #242's 30% bar.**

---

## Phase 1 — Baseline & marker hygiene

**Goal:** make the suite observable and cut the obvious dead weight before any
rearchitecting.

### 1a — Capture a baseline

- Run E2E with `--durations=0 --durations-min=1.0` and upload pytest's JSON
  report as a CI artifact.
- Keep the existing `--export-traces` OTEL plumbing.
- Commit the per-test duration table to a comment on #242 so future changes
  can be measured against it.

Without this, no claim of "X% faster" is defensible.

### 1b — Marker audit

Walk each of the 22 files against the AGENTS.md heuristic ("every action goes
through `client.X.Y()` / `kubectl` / `kr8s` and the test never calls
dual-entrypoint scenario methods → `api_only`"). Strong candidates already
identified:

- **Almost certainly `api_only`** (currently dual): `test_admin_user_crud`,
  `test_admin_group_membership`, `test_auth_lifecycle`, `test_cli_auth`,
  `test_service_discovery`, `test_backup_restore_databases`,
  `test_deployment_timeline`. None have UI assertions — all are SDK/API
  reads.
- **Already correctly marked**: `test_deployment_typed_input` (api_only),
  `test_pod_component_attribution` (api_only), the 4 UI-only header/label
  tests.
- **Genuinely dual** (must run both variants): `test_deploy_app`,
  `test_environment_update`, `test_ingress_controller`,
  `test_deployment_env_vars`, `test_pod_scheduling`, `test_backup_restore`,
  `test_delete_deployment_*`.

Expected: ~7 more files become `api_only` → the UI job runs ~13 files
instead of ~20.

### 1c — Guardrail

Add a `pytest_collection_modifyitems` hook (or a lint) that **fails CI** if a
new `mark.ci` E2E test lacks an explicit `api_only` / `ui_only` / `dual`
decision. Forces future authors to pick.

---

## Phase 2 — Test grouping & shared-deployment policy

**Goal:** stop creating fresh deployments for tests that only *read* state.
Establish explicit "test pods" so future tests slot into the right cost bucket.

### 2a — Classify every test into one of three sharing tiers

| Tier | Setup | Sample tests |
|---|---|---|
| **Read-only** — assert on shared state, no mutation | `styrmin_resources` + a pre-existing `deployed_simple_app` | `deployment_detail_header`, `deploy_form_driver_label`, `deployment_pods_tab`, `pod_component_attribution`, `service_discovery`, `driver_detail`, `deployment_timeline` (read), parts of `cli_auth` |
| **Isolated mutation** — creates/deletes its own deployment | own `deployment_*` fixture | `deploy_app`, `delete_deployment_*`, `environment_update`, `deployment_env_vars`, `deployment_typed_input`, `deploy_semaphore`, `ingress_controller` |
| **Heavy/exclusive** — must run alone (Velero, Infrahub, db-test backups) | dedicated session fixture | `backup_restore`, `backup_restore_databases`, infrahub deployment |

This tiering is the prerequisite for Phase 3 — without it, parallel
scheduling would be guesswork.

### 2b — Consolidate the Read-only tier UI-side

The four small UI-only files (`deployment_detail_header`,
`deploy_form_driver_label`, `deployment_pods_tab`, `driver_detail`) each pay
~the same per-test setup overhead (Playwright page-load, auth cookie inject,
navigation). Merge into `test_ui_smoke.py` with one fixture and multiple
test functions to cut ~3× per-test fixed overhead.

**Non-goal:** we are NOT collapsing meaningful tests into shapeless
mega-tests. The merge is strictly for the trivially-mergeable UI smoke tests
above.

### 2c — Write down the deployment-sharing policy

New page `dev/guides/e2e-deployment-sharing.md`:

- Read-only tier MUST reuse `deployed_simple_app` (or equivalent shared
  fixture); creating a fresh deployment for a read-only assertion is a
  review-blocker.
- Mutation tier MUST create its own deployment with a unique name.
- Heavy tier MUST live in its own file *and* be flagged so Phase 3's
  scheduler can isolate it.

Add a CONTEXT.md term: **"test pod"** = the set of tests that share one
vcluster + styrmin install in CI.

### 2d — New tier markers

Add `@pytest.mark.shared_deployment` / `@pytest.mark.isolated_deployment` /
`@pytest.mark.heavy` (orthogonal to `api_only` / `ui_only`). Phase 3's CI
matrix keys off these markers; without them, the matrix YAML would have to
hand-list test files.

---

## Phase 3 — Matrix sharding (the headline win)

**Goal:** stop having the slower job's wall-clock be `Σ(test_durations) ÷ 1`.

### Approach: matrix-sharded CI jobs, one vcluster per shard

Restructure `e2e-tests-api` / `e2e-tests-ui` as **matrix jobs** keyed by a
shard label:

```yaml
strategy:
  fail-fast: false
  matrix:
    shard: [readonly, mutation-small, mutation-large, ingress, backup, infrahub]
    entrypoint: [api, ui]
    exclude:
      - { shard: infrahub, entrypoint: ui }      # api_only
      # additional exclusions per Phase 1 marker audit
```

Each cell runs `pytest -m "ci and shard_<name>" -k "<entrypoint>-chromium"`
on its own runner with its own vcluster.

### Why matrix sharding over pytest-xdist within a single job

- **No shared-fixture race.** Each shard's vcluster is built fresh; no
  cross-worker port-forward collisions, no shared chart-server, no fighting
  over `styrmin-server` port.
- **`--pdb` workflow unchanged.** Each shard still runs single-threaded
  inside its job; AGENTS.md's `--pdb` recipe and the `e2e-troubleshoot`
  skill keep working with zero edits. pytest-xdist would trap stdin and
  break this.
- **Failure attribution is clean.** GitHub Actions shows 6 green/red
  lights per entrypoint; you know *which group* broke instead of grepping
  one giant interleaved log.
- **Easy to tune.** Slow shard? Split it. Cheap shard? Merge. Done in YAML,
  no Python.
- **`STYRMIN_IMAGE_VER` per-runner tagging already accommodates this** —
  each shard gets its own image tag, no collision on shared self-hosted
  runners.

### Cost

N × (vcluster boot + helm install + image build) instead of 2× — but in
parallel, so wall-clock = max not sum. Concretely: today 2 jobs × ~6 min
setup = 6 min wall-clock setup. With 6 shards × 2 entrypoints (minus
exclusions) ≈ 10–12 cells, ~6 min wall-clock setup (all parallel), but ~6×
the runner-minutes. Acceptable on the `huge-runners` group.

### Shard scheme

| Shard | Tests | Reason |
|---|---|---|
| `readonly` | `test_ui_smoke` (Phase 2 merge), `service_discovery`, `pod_component_attribution`, `driver_detail`, `cli_auth`, `auth_lifecycle`, `admin_user_crud`, `admin_group_membership`, `deployment_timeline` | All read shared deployment — single vcluster, single `deployed_simple_app`, runs fast |
| `mutation-small` | `deploy_app`, `delete_deployment_api`, `delete_deployment_ui`, `deploy_form_driver_label`, `deploy_semaphore`, `deployment_pods_tab`, `deployment_detail_header`, `deployment_typed_input` | Each creates own deployment but short |
| `mutation-large` | `deployment_env_vars`, `environment_update`, `pod_scheduling` | Heavy mutation; env-vars (682 LOC × parametrize) is the suite's longest file |
| `ingress` | `test_ingress_controller` | 736 LOC, by itself a runaway — own shard |
| `backup` | `test_backup_restore`, `test_backup_restore_databases` | Velero + MinIO, can interfere with other deployments — isolate |
| `infrahub` | `deployed_infrahub_app` consumers | Heavy app — isolate |

### Expected payoff

Wall-clock for the slowest shard becomes the new bottleneck. Today's ~20 min
likely → ~8–10 min for the heaviest shard (`ingress` or `mutation-large`).
**35–55% wall-clock reduction.**

### Decided-against alternative: pytest-xdist with worker-scoped vcluster

Rejected for Phase 3:

- Conftest gets a hairy rewrite: every `scope="session"` fixture must become
  `scope="session"` per worker without colliding on `tmp_path_factory`,
  port-forwards, or helm install.
- 4+ vclusters on one runner = Docker/kubelet/inotify pressure on the host.
  The existing `_portforward` retry loop already exists because port
  allocation races; xdist multiplies the race surface.
- `--pdb` breaks under xdist (pytest-xdist traps stdin) — would need a
  documented "single-worker mode" toggle for debugging, contradicting
  AGENTS.md.
- Failure attribution: one interleaved log, four workers' worth of
  `_dump_namespace_logs` from four namespaces.

Reconsider only if matrix-sharding falls short of #242's 30% target.

---

## Phase 4 — Docs & guardrails

**Goal:** make the new shape self-perpetuating. None of Phase 1–3's wins
survive if the next contributor adds a test that ignores the markers.

### 4a — New guide

`dev/guides/e2e-parallelism.md` covering: the shard scheme, what
`shared_deployment` / `isolated_deployment` / `heavy` mean, which shard
each marker routes to, how to add a new test (decision tree: read-only? →
readonly shard; mutation? → mutation shard; spawns own heavy infra? → its
own shard), and the `--pdb` recipe (unchanged — confirm explicitly so
future readers don't fear matrix sharding).

### 4b — AGENTS.md updates

Update the "Dual-entrypoint scope" section to reference the new tier
markers, and "Debugging E2E Tests" to confirm `--pdb` still works per-shard.
Add a one-liner pointer from AGENTS.md → the new guide.

### 4c — CONTEXT.md

Add the term **"test pod"** = one shard's worth of tests sharing one
vcluster.

### 4d — ADR

Short ADR (`dev/adr/00NN-e2e-matrix-sharding.md`) recording why we chose
matrix sharding over xdist, what we'd reconsider, and the
baseline → post-change numbers.

### 4e — CI guardrail

A `conftest.py`-level `pytest_collection_modifyitems` that:

- Fails collection if any `mark.ci` test lacks both an entrypoint marker
  (`api_only` / `ui_only` or explicit "dual" placeholder) and a tier
  marker (`shared_deployment` / `isolated_deployment` / `heavy`).
- Verifies each shard label in the CI YAML corresponds to a real marker
  (no typo'd shards).
- Optionally: prints the per-shard count at collection time so a PR adding
  5 tests to one shard is visible in CI logs.

### 4f — Performance regression check

Diff each run's per-test durations against a stored baseline (committed
alongside the ADR) and emit a warning if a single test grew >50%. Not a
blocker — visibility only. The OTEL pipeline already exists; this is
plumbing.

---

## Out of scope (deferred follow-ups)

- **Pre-built styrmin image registry** (Option C in design discussion).
  Push the per-commit image once to a local registry, then `helm install`
  references it from every shard. Saves ~30–60s × N shards. Revisit if
  Phase 3 numbers come in light.
- **pytest-xdist with worker-scoped vcluster** (Option B). Revisit only if
  matrix-sharding hits a runner-cost ceiling.
- **Vcluster snapshot caching, Velero/MinIO consolidation across shards.**
- **Killing the `[ui-chromium]` parametrize axis entirely** in favor of a
  single dual-aware test runner.

## Risks

- **Cross-shard fixture coupling.** Velero's `BackupStorageLocation` and
  the MinIO instance are created inside `styrmin_resources` at session
  scope. If any test relies on backup state created by a prior test in a
  *different* shard, the matrix split will break it. Phase 1's baseline
  run should surface this; if it does, either merge the shards involved
  or refactor the cross-test coupling.
- **Runner-minute cost.** Matrix sharding ~6× the runner-minutes vs.
  today. Acceptable on `huge-runners` group; would not be acceptable on
  GitHub-hosted runners.
- **Shard-balance drift.** Without 4e's count visibility, one shard
  silently inflates and re-becomes the bottleneck within a release cycle.

## Open questions

None — all design decisions resolved in the brainstorming session
(matrix-sharding chosen over xdist; 6 shards per entrypoint; image-cache
out of scope for the first pass).

## Acceptance criteria (from #242)

- [ ] Baseline + post-refactor numbers documented (issue comment or
      `dev/knowledge/e2e-performance.md`).
- [ ] CI wall-clock for `e2e-tests-api` and `e2e-tests-ui` measurably
      lower on `develop` after the change lands; state the % drop in the
      merging PR.
- [ ] All existing E2E scenarios still execute (no skips introduced);
      suite remains green on `develop`.
- [ ] `api_only` / `ui_only` markers correctly applied across the suite;
      no test runs `[ui-chromium]` when its actions never touch the UI.
- [ ] If `pytest-xdist` is adopted (NOT the chosen path here, but for
      completeness): `vcluster` / registry / helm-server / `styrmin-server`
      fixtures move from `session` to a scope compatible with parallel
      workers, and `--pdb` still works for single-test runs. **N/A under
      matrix-sharding** — the `--pdb` workflow is preserved by design.
- [ ] `dev/guides/` (or `AGENTS.md`) updated with the new
      "how E2E parallelism / sharing works" guidance.
