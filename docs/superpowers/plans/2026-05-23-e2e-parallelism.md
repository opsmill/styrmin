# E2E Test Parallelism & Execution Speedup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the slower E2E CI job's wall-clock by 30–65% by tightening dual-entrypoint markers, consolidating trivially-mergeable UI smoke tests, and replacing the two monolithic E2E jobs with a 6-shard matrix — each shard booting its own vcluster.

**Architecture:** Marker-driven test routing. Every `@pytest.mark.ci` E2E test gets exactly one bare-name shard marker — one of `shard_readonly`, `shard_mutation_small`, `shard_mutation_large`, `shard_ingress`, `shard_backup`, `shard_infrahub`. A `pytest_collection_modifyitems` hook fails CI if a test is missing the marker. CI matrix dispatches each shard to its own runner with `pytest -m "ci and shard_<name>"`. **Why bare names, not `@pytest.mark.shard("readonly")`?** Pytest's `-m EXPR` evaluator filters on marker *names* only — it does not match against mark arguments. The parameterized form looks cleaner but cannot be selected via `-m`. Bare names are the only form that actually routes tests in CI.

**Tech Stack:** Python 3.14, pytest, pytest-asyncio, kr8s, vcluster (Docker driver), Playwright, GitHub Actions matrix strategy.

**Spec:** [`docs/superpowers/specs/2026-05-23-e2e-parallelism-design.md`](../specs/2026-05-23-e2e-parallelism-design.md) · **Tracking issue:** [opsmill/styrmin#242](https://github.com/opsmill/styrmin/issues/242)

---

## Plan-level notes

**Marker consolidation (clarification vs. spec):** The spec's Phase 2d describes both "tier markers" (`shared_deployment` / `isolated_deployment` / `heavy`) and Phase 3's "shard markers" (`shard_<name>` × 6). Since the 6 shard names already encode the tier semantically (e.g., `readonly` ≡ shared_deployment), this plan implements **shard markers only** — one marker family, one CI dispatch key. The tier concept becomes a section in the deployment-sharing guide rather than a separate marker. If you want both, push back before Task 3.

**Shard names use underscores throughout** (e.g., `mutation_small`, not a hyphenated form) so the marker name matches the matrix-cell label without translation. The CI job *display* name can still use hyphens via a string transform if you want.

**File path conventions:** All E2E test files live in `backend/tests/e2e/`. The repo's working directory is the project root (the worktree at `thorn-barber/`).

**TDD note:** This refactor is mostly metadata + CI-config work. TDD applies cleanly to one piece — the conftest collection-hook guardrail (Task 4). Other tasks have validation by running the existing E2E suite or pytest collection only.

**Branch:** Work proceeds on the current `thorn-barber` branch where the spec was committed, or a fresh branch off `develop` per project convention. The plan does not prescribe.

---

## File Structure

**Files created:**

- `backend/tests/e2e/test_ui_smoke.py` — merged UI-only smoke tests (Task 5)
- `dev/guides/e2e-deployment-sharing.md` — when to share vs. create deployments (Task 6)
- `dev/guides/e2e-parallelism.md` — shard scheme + decision tree (Task 8)
- `dev/adr/00NN-e2e-matrix-sharding.md` — recorded decision (Task 10)
- `tasks/check_e2e_regressions.py` — optional GHA-API regression check (Task 11)

**Files modified:**

- `pyproject.toml` — register `shard` marker (Task 1)
- `backend/tests/e2e/conftest.py` — collection guardrail (Task 4)
- `backend/tests/e2e/test_*.py` (~22 files) — `shard_*` markers (Task 3); `api_only(...)` markers (Task 2)
- `.github/workflows/ci.yml` — matrix-sharded `e2e-tests-*` jobs (Task 7)
- `AGENTS.md` — pointer to new guides (Task 9)
- `CONTEXT.md` — "test pod" / "shard" entries (Task 9)

**Files deleted (consolidated into `test_ui_smoke.py`):**

- `backend/tests/e2e/test_deployment_detail_header.py`
- `backend/tests/e2e/test_deploy_form_driver_label.py`
- `backend/tests/e2e/test_deployment_pods_tab.py`
- `backend/tests/e2e/test_driver_detail.py`

---

## Task 1: Register the 6 shard markers

**Files:**

- Modify: `pyproject.toml` (the `[tool.pytest.ini_options].markers` list)

- [ ] **Step 1: Open `pyproject.toml` and locate the existing markers block**

The current block (already verified to exist):

```toml
[tool.pytest.ini_options]
markers = [
    "e2e: end-to-end tests requiring a vCluster and external dependencies",
    "ci: e2e tests included in the CI pipeline",
    "api_only(reason): scenario runs only through the API entrypoint; [ui] variant is skipped with the given reason",
    "ui_only(reason): scenario runs only through the UI entrypoint; [api] variant is skipped with the given reason",
]
```

- [ ] **Step 2: Append the 6 bare-name shard markers**

Replace the markers list with:

```toml
markers = [
    "e2e: end-to-end tests requiring a vCluster and external dependencies",
    "ci: e2e tests included in the CI pipeline",
    "api_only(reason): scenario runs only through the API entrypoint; [ui] variant is skipped with the given reason",
    "ui_only(reason): scenario runs only through the UI entrypoint; [api] variant is skipped with the given reason",
    "shard_readonly: CI shard for read-only tests sharing the session deployment. See dev/guides/e2e-parallelism.md.",
    "shard_mutation_small: CI shard for short tests that create/delete their own deployment.",
    "shard_mutation_large: CI shard for long mutation tests (env-vars matrix, environment_update, pod_scheduling).",
    "shard_ingress: CI shard for the standalone ingress-controller suite.",
    "shard_backup: CI shard for Velero / MinIO heavy tests (cluster-wide state).",
    "shard_infrahub: CI shard for the Infrahub app stack.",
]
```

- [ ] **Step 3: Verify pytest accepts the markers syntactically**

```bash
uv run pytest --collect-only backend/tests/e2e -q 2>&1 | tail -5
```

Expected: no `PytestUnknownMarkWarning` for `shard_*`. Collection succeeds (warnings about individual tests missing the marker are expected — those get fixed in Task 3).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "test(e2e): register shard_* markers for CI matrix routing"
```

---

## Task 2: Convert 6 audit-candidate files to `api_only`

**Goal:** Phase 1a marker hygiene. These six files drive only the SDK / kubectl / kr8s — the UI variant just re-runs the same SDK calls. Removing them from the UI job is the biggest free win.

**Files (each verified to currently lack `api_only` / `ui_only` at module scope):**

- `backend/tests/e2e/test_admin_user_crud.py`
- `backend/tests/e2e/test_admin_group_membership.py`
- `backend/tests/e2e/test_auth_lifecycle.py`
- `backend/tests/e2e/test_service_discovery.py`
- `backend/tests/e2e/test_backup_restore_databases.py`
- `backend/tests/e2e/test_deployment_timeline.py`
- [ ] **Step 1: Verify each file is genuinely api-only**

For each file, read it and confirm:

- No `page.click(...)`, `page.locator(...)`, or `expect(...)` from Playwright.
- No use of `scenario_driver.create_deployment` / `upgrade_deployment` / `start_components` / `create_backup` (the dual-entrypoint methods listed in AGENTS.md).
- All actions go through `client.X.Y()`, `kubectl`, or `kr8s`.

If a file does drive the UI, **do not mark it `api_only`** — leave it dual and note the exception in the PR description.

```bash
for f in test_admin_user_crud test_admin_group_membership test_auth_lifecycle test_service_discovery test_backup_restore_databases test_deployment_timeline; do
  echo "=== $f ===" && grep -c "page\.\|expect(\|scenario_driver\." backend/tests/e2e/${f}.py
done
```

Expected: most files show 0 for `page.` and `expect(`. `test_deployment_timeline` may show `scenario_driver.` references — read the file and verify those are only read-style calls (`get_deployment`, `list_events`), not mutations.

- [ ] **Step 2: Add `api_only` to each file's module-level `pytestmark`**

For files that already have `pytestmark = [pytest.mark.ci]`, expand it. For files that use per-function `@pytest.mark.ci`, add a module-level pytestmark.

Example pattern — apply to each file:

```python
# At module scope, replacing the existing pytestmark assignment:
pytestmark = [
    pytest.mark.ci,
    pytest.mark.api_only(
        reason="All actions go through the SDK / kubectl / kr8s; "
        "the [ui-chromium] variant would re-run the same code path.",
    ),
]
```

Customize the `reason` to the file's actual content (e.g., for `test_admin_user_crud.py`: "Admin user CRUD is SDK-only; no admin UI is exercised here.").

- [ ] **Step 3: Verify collection now skips these tests under `-k ui-chromium`**

```bash
uv run pytest --collect-only -m ci -k "ui-chromium" backend/tests/e2e/test_admin_user_crud.py -q
```

Expected: `0 tests collected` (or only a `skipped` marker). The file is no longer part of the UI job.

- [ ] **Step 4: Run one representative file's api variant locally to confirm nothing regressed**

```bash
uv run pytest -v -k "api-chromium" backend/tests/e2e/test_admin_user_crud.py 2>&1 | tail -20
```

Expected: tests still run and pass (or fail for the same reasons they did before — this task changes metadata, not behavior).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/test_admin_user_crud.py \
        backend/tests/e2e/test_admin_group_membership.py \
        backend/tests/e2e/test_auth_lifecycle.py \
        backend/tests/e2e/test_service_discovery.py \
        backend/tests/e2e/test_backup_restore_databases.py \
        backend/tests/e2e/test_deployment_timeline.py
git commit -m "test(e2e): mark SDK-only suites as api_only

These six suites drive only the SDK / kubectl / kr8s. The
[ui-chromium] variant added no coverage — every action went
through the same SDK call path. Skipping the UI variant cuts
~7 files off the UI job's collection.

Refs: opsmill/styrmin#242"
```

---

## Task 3: Apply shard markers to every CI-tagged E2E test

**Goal:** Phase 2's tiering, simplified to single-marker form. Every `@pytest.mark.ci` test gets exactly one bare-name shard marker at module scope.

**Shard assignment (from spec §Phase 3):**

| Marker | Files |
|---|---|
| `shard_readonly` | `test_service_discovery.py`, `test_pod_component_attribution.py`, `test_driver_detail.py`*, `test_cli_auth.py`, `test_auth_lifecycle.py`, `test_admin_user_crud.py`, `test_admin_group_membership.py`, `test_deployment_timeline.py` |
| `shard_mutation_small` | `test_deploy_app.py`, `test_delete_deployment_api.py`, `test_delete_deployment_ui.py`, `test_deploy_form_driver_label.py`*, `test_deploy_semaphore.py`, `test_deployment_pods_tab.py`*, `test_deployment_detail_header.py`*, `test_deployment_typed_input.py` |
| `shard_mutation_large` | `test_deployment_env_vars.py`, `test_environment_update.py`, `test_pod_scheduling.py` |
| `shard_ingress` | `test_ingress_controller.py` |
| `shard_backup` | `test_backup_restore.py`, `test_backup_restore_databases.py` |
| `shard_infrahub` | (none yet — the existing infrahub-deployed tests live inside other files; if any file is added that consumes `deployed_infrahub_app` exclusively, route it here) |

\* These four files get merged into `test_ui_smoke.py` in Task 5; tag them now anyway so the suite is consistent during the transition.

- [ ] **Step 1: For each file, add the shard marker at module scope**

Example for `test_service_discovery.py` (currently uses per-function `@pytest.mark.ci`):

```python
pytestmark = [
    pytest.mark.ci,
    pytest.mark.shard_readonly,
]
```

For files already with `pytestmark = [pytest.mark.ci, pytest.mark.api_only(...)]` from Task 2, append:

```python
pytestmark = [
    pytest.mark.ci,
    pytest.mark.api_only(reason="..."),
    pytest.mark.shard_readonly,
]
```

Walk the table above row by row. Commit per shard (six commits total) so each commit is reviewable in isolation.

- [ ] **Step 2: After each shard's commit, verify collection routes correctly**

```bash
uv run pytest --collect-only -m "ci and shard_readonly" backend/tests/e2e -q | tail -10
```

Expected: only the files listed for that shard appear in the collected set. Repeat for each shard name.

- [ ] **Step 3: Commit per shard**

Example for the readonly shard:

```bash
git add backend/tests/e2e/test_service_discovery.py \
        backend/tests/e2e/test_pod_component_attribution.py \
        backend/tests/e2e/test_driver_detail.py \
        backend/tests/e2e/test_cli_auth.py \
        backend/tests/e2e/test_auth_lifecycle.py \
        backend/tests/e2e/test_admin_user_crud.py \
        backend/tests/e2e/test_admin_group_membership.py \
        backend/tests/e2e/test_deployment_timeline.py
git commit -m "test(e2e): assign shard_readonly to read-only suites

Refs: opsmill/styrmin#242"
```

Repeat for each of the other five shards.

---

## Task 4: Write the conftest collection guardrail (TDD)

**Goal:** Phase 1b + Phase 4e combined. A pytest hook that fails collection if any `mark.ci` E2E test lacks both an entrypoint marker (`api_only` / `ui_only` / explicit dual-via-no-marker) AND a `shard` marker. This locks in the marker discipline so a new contributor can't silently regress the matrix.

**Decision: how to model "this test is explicitly dual"** — easiest: a test that has neither `api_only` nor `ui_only` is implicitly dual. The guardrail only requires the `shard` marker explicitly. No "dual" marker needed.

**Files:**

- Modify: `backend/tests/e2e/conftest.py` — add `pytest_collection_modifyitems` hook near the top

- Create: `backend/tests/e2e/test_guardrail.py` — the test that exercises the hook

- [ ] **Step 1: Write a failing test for the guardrail**

Create `backend/tests/e2e/test_guardrail.py`:

```python
"""Tests for the E2E-suite collection guardrail.

Runs as a normal pytest, not part of CI. Uses pytester to drive a fresh
pytest collection inside a temp directory and assert the guardrail rejects
tests that lack the required shard_* marker.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]


_INI = """
[pytest]
markers =
    ci: foo
    shard_readonly: foo
    shard_mutation_small: foo
    shard_mutation_large: foo
    shard_ingress: foo
    shard_backup: foo
    shard_infrahub: foo
"""


def test_collection_fails_when_ci_test_lacks_shard_marker(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import enforce_shard_markers  # noqa: F401


def pytest_collection_modifyitems(config, items):
    enforce_shard_markers(config, items)
""",
        test_bad="""
import pytest


@pytest.mark.ci
def test_missing_shard():
    pass
""",
    )
    pytester.makeini(_INI)
    result = pytester.runpytest("--collect-only")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*missing required @pytest.mark.shard_*test_missing_shard*"])


def test_collection_passes_when_ci_test_has_shard_marker(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import enforce_shard_markers  # noqa: F401


def pytest_collection_modifyitems(config, items):
    enforce_shard_markers(config, items)
""",
        test_good="""
import pytest


@pytest.mark.ci
@pytest.mark.shard_readonly
def test_has_shard():
    pass
""",
    )
    pytester.makeini(_INI)
    result = pytester.runpytest("--collect-only")
    assert result.ret == 0


def test_collection_rejects_multiple_shard_markers(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import enforce_shard_markers  # noqa: F401


def pytest_collection_modifyitems(config, items):
    enforce_shard_markers(config, items)
""",
        test_double="""
import pytest


@pytest.mark.ci
@pytest.mark.shard_readonly
@pytest.mark.shard_backup
def test_double_marked():
    pass
""",
    )
    pytester.makeini(_INI)
    result = pytester.runpytest("--collect-only")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*has multiple shard markers*test_double_marked*"])
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
uv run pytest backend/tests/e2e/test_guardrail.py -v
```

Expected: import error — `cannot import name 'enforce_shard_markers' from 'tests.e2e.conftest'`. That's the red.

- [ ] **Step 3: Implement the guardrail in `conftest.py`**

Open `backend/tests/e2e/conftest.py` and add this near the top, after the existing `pytest_configure` hook (around line 48–55):

```python
_VALID_SHARDS = frozenset({
    "shard_readonly",
    "shard_mutation_small",
    "shard_mutation_large",
    "shard_ingress",
    "shard_backup",
    "shard_infrahub",
})


def enforce_shard_markers(
    config: pytest.Config,  # noqa: ARG001
    items: list[pytest.Item],
) -> None:
    """Fail collection if any ``mark.ci`` test lacks exactly one ``shard_*`` marker.

    Locks in the matrix-sharding contract: every CI-included E2E test MUST
    name the shard it routes to (see ``dev/guides/e2e-parallelism.md``).
    A test that lacks the marker would silently drop out of every shard
    and disappear from coverage; rejecting it at collection time is the
    only place to catch this before CI is green-on-nothing.
    """
    errors: list[str] = []
    for item in items:
        if "ci" not in item.keywords:
            continue
        shard_marks = [
            m.name for m in item.iter_markers() if m.name in _VALID_SHARDS
        ]
        if not shard_marks:
            errors.append(
                f"{item.nodeid}: missing required @pytest.mark.shard_<name> — "
                f"one of {sorted(_VALID_SHARDS)}; "
                f"see dev/guides/e2e-parallelism.md"
            )
            continue
        if len(shard_marks) > 1:
            errors.append(
                f"{item.nodeid}: has multiple shard markers {shard_marks}; "
                f"exactly one is allowed"
            )
    if errors:
        raise pytest.UsageError(
            "E2E shard marker check failed:\n  " + "\n  ".join(errors)
        )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """E2E suite entry point for the shard-marker guardrail."""
    enforce_shard_markers(config, items)
```

- [ ] **Step 4: Re-run the guardrail tests**

```bash
uv run pytest backend/tests/e2e/test_guardrail.py -v
```

Expected: all three tests pass.

- [ ] **Step 5: Run the full E2E collection to make sure no real test was missed in Task 3**

```bash
uv run pytest --collect-only backend/tests/e2e -q 2>&1 | tail -30
```

Expected: collection succeeds. If it fails with "missing required @pytest.mark.shard", the listed file was missed in Task 3 — go back and tag it.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/e2e/conftest.py backend/tests/e2e/test_guardrail.py
git commit -m "test(e2e): enforce shard markers via collection hook

Adds pytest_collection_modifyitems that rejects any @pytest.mark.ci
test lacking a valid @pytest.mark.shard_<name>. Prevents new tests
from silently dropping out of the matrix.

Refs: opsmill/styrmin#242"
```

---

## Task 5: Merge the 4 UI-only smoke tests into `test_ui_smoke.py`

**Goal:** Phase 2b. Four tiny UI-only files each pay the same per-test Playwright setup overhead. Merging them into one file with one fixture cuts ~3× per-test fixed cost.

**Files:**

- Create: `backend/tests/e2e/test_ui_smoke.py`

- Delete: `backend/tests/e2e/test_deployment_detail_header.py`, `test_deploy_form_driver_label.py`, `test_deployment_pods_tab.py`, `test_driver_detail.py`

- [ ] **Step 1: Read each of the 4 files to capture their test functions verbatim**

```bash
cat backend/tests/e2e/test_deployment_detail_header.py \
    backend/tests/e2e/test_deploy_form_driver_label.py \
    backend/tests/e2e/test_deployment_pods_tab.py \
    backend/tests/e2e/test_driver_detail.py
```

Note each file's:

- Imports (page object modules, regex helpers)
- Test function signature (fixture parameters)
- Test body
- [ ] **Step 2: Create `backend/tests/e2e/test_ui_smoke.py` consolidating all four**

Skeleton structure (fill in each test body from Step 1's read):

```python
"""UI smoke suite — small, read-mostly UI assertions sharing one deployment.

Each test here was previously its own file (test_deployment_detail_header.py,
test_deploy_form_driver_label.py, test_deployment_pods_tab.py,
test_driver_detail.py). Merging cuts per-test Playwright setup overhead and
keeps the read-only shard tight.

Add new UI-smoke assertions here when they:
- Are purely UI rendering / click-flow assertions (no API equivalent).
- Read the session-shared deployment without mutating it.
- Run in under ~10 seconds.

Heavier UI flows (auth, multi-step forms) keep their own files.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from tests.e2e.pages.deploy_form import DeployFormPage
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.pods_tab import PodsTabPage

if TYPE_CHECKING:
    from playwright.async_api import Page

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

pytestmark = [
    pytest.mark.ci,
    pytest.mark.ui_only(
        reason="UI smoke assertions — rendered DOM only; no SDK equivalent.",
    ),
    pytest.mark.shard_readonly,
]


# ---- from test_deployment_detail_header.py ----
async def test_deployment_header_shows_driver_name(...):
    # PASTE the original body here, unchanged.
    ...


# ---- from test_deploy_form_driver_label.py ----
async def test_deploy_form_shows_driver_label_after_selection(...):
    # PASTE the original body here, unchanged.
    ...


# ---- from test_deployment_pods_tab.py ----
async def test_pods_tab_copy_logs_command(...):
    # PASTE the original body here, unchanged.
    ...


# ---- from test_driver_detail.py ----
async def test_driver_detail_inspects_versions_via_tabs(...):
    # PASTE the original body here, unchanged.
    ...
```

**Key rule:** Copy each test function body byte-for-byte. Do not refactor while merging — that risks behavior change. The merge is a pure relocation.

- [ ] **Step 3: Delete the four original files**

```bash
git rm backend/tests/e2e/test_deployment_detail_header.py \
       backend/tests/e2e/test_deploy_form_driver_label.py \
       backend/tests/e2e/test_deployment_pods_tab.py \
       backend/tests/e2e/test_driver_detail.py
```

- [ ] **Step 4: Verify collection picks up the merged file with all four tests**

```bash
uv run pytest --collect-only backend/tests/e2e/test_ui_smoke.py -q
```

Expected: 4 tests collected (one per merged function), each parameterized `[ui-chromium]` (no `[api-chromium]` since `ui_only`).

- [ ] **Step 5: Run the merged suite locally if you have a vcluster available**

```bash
uv run pytest -v -k "ui-chromium" backend/tests/e2e/test_ui_smoke.py --pdb
```

Expected: all four tests pass. If one fails, compare its body byte-for-byte against the original file (recover from git: `git show HEAD~:backend/tests/e2e/test_deployment_detail_header.py`).

- [ ] **Step 6: Commit**

```bash
git add backend/tests/e2e/test_ui_smoke.py
git commit -m "test(e2e): consolidate UI smoke tests into test_ui_smoke.py

Merges test_deployment_detail_header, test_deploy_form_driver_label,
test_deployment_pods_tab, and test_driver_detail into a single file
sharing one Playwright fixture chain. Bodies copied verbatim — no
behaviour change.

Refs: opsmill/styrmin#242"
```

---

## Task 6: Write `dev/guides/e2e-deployment-sharing.md`

**Goal:** Phase 2c — codify the read-only vs. isolated-mutation vs. heavy/exclusive distinction so future tests slot into the right shard.

**Files:**

- Create: `dev/guides/e2e-deployment-sharing.md`

- [ ] **Step 1: Write the guide**

Create `dev/guides/e2e-deployment-sharing.md` with this content:

```markdown
# E2E Deployment-Sharing Policy

E2E tests fall into one of three sharing tiers. Each tier maps to one
or more CI shards (see `e2e-parallelism.md` for the shard scheme).

## Tiers

### Read-only

The test asserts on state already produced by the session-scoped
`styrmin_resources` + a session-scoped `deployed_simple_app` (or
equivalent). It MUST NOT create, modify, or delete deployments.

- **Shard:** `readonly`
- **Examples:** `test_service_discovery`, `test_pod_component_attribution`,
  `test_ui_smoke`, `test_driver_detail`, `test_deployment_timeline` (read
  variants), the cli-auth and admin-user/group suites.
- **Review rule:** A read-only test that creates its own deployment is a
  review-blocker. Refactor to consume the shared fixture.

### Isolated mutation

The test creates and tears down its own deployment with a unique name.
Multiple isolated-mutation tests can run in the same shard but each one
must not depend on another's state.

- **Shard:** `mutation_small` (short tests), `mutation_large` (long
  tests like env-vars matrix, environment_update, pod_scheduling), or
  `ingress` (the standalone ingress-controller suite).
- **Examples:** `test_deploy_app`, `test_delete_deployment_*`,
  `test_environment_update`.
- **Review rule:** Reuse `deployed_simple_app` if your test only reads —
  do not create a fresh deployment just for an isolated assertion.

### Heavy / exclusive

The test depends on cluster-wide infrastructure that conflicts with
other tests: Velero backups, MinIO, the Infrahub stack. It MUST live in
its own file and its own shard.

- **Shard:** `backup` (Velero / MinIO) or `infrahub` (the Infrahub
  app stack).
- **Examples:** `test_backup_restore`, `test_backup_restore_databases`.
- **Review rule:** Adding a new "heavy" test category? Open an ADR
  first — the matrix YAML in `.github/workflows/ci.yml` needs a new
  shard entry.

## Decision tree

1. Does the test mutate state? → No: `readonly`.
2. Does it touch Velero, MinIO, or Infrahub? → Yes: `backup` or
   `infrahub`.
3. Is it an ingress-controller test? → Yes: `ingress`.
4. Is it expected to run for >2 minutes? → Yes: `mutation_large`,
   otherwise `mutation_small`.

## Adding a new test

Every `@pytest.mark.ci` E2E test MUST carry exactly one bare-name
shard marker (`shard_readonly`, `shard_mutation_small`,
`shard_mutation_large`, `shard_ingress`, `shard_backup`, or
`shard_infrahub`). The conftest collection hook
(`enforce_shard_markers`) rejects the suite if any test is missing
the marker or carries more than one.

Apply at module scope when all tests in the file share the same
shard:

\`\`\`python
pytestmark = [
    pytest.mark.ci,
    pytest.mark.api_only(reason="..."), # if applicable
    pytest.mark.shard_readonly,
]
\`\`\`
```

(Note: in the actual file, use real triple-backticks instead of escaped ones.)

- [ ] **Step 2: Commit**

```bash
git add dev/guides/e2e-deployment-sharing.md
git commit -m "docs(e2e): add deployment-sharing policy guide

Refs: opsmill/styrmin#242"
```

---

## Task 7: Rewrite the CI E2E jobs as a 6-shard matrix

**Goal:** Phase 3 — the headline wall-clock win. Replace the two monolithic `e2e-tests-api` / `e2e-tests-ui` jobs with a matrix of (shard × entrypoint) cells, each on its own runner with its own vcluster.

**Files:**

- Modify: `.github/workflows/ci.yml` (the `e2e-tests-api` and `e2e-tests-ui` job definitions, ~L200–L280)

- [ ] **Step 1: Read the current `e2e-tests-api` and `e2e-tests-ui` jobs**

```bash
sed -n '180,330p' .github/workflows/ci.yml
```

Note: the two jobs are nearly identical except for the UI job's Playwright install and `no-netlink shim` steps, and the `-k api-chromium` vs `-k ui-chromium` filter on the pytest command.

- [ ] **Step 2: Define the matrix strategy**

Replace the two job blocks with a single combined matrix job. Insert the following in place of the current `e2e-tests-api` and `e2e-tests-ui` blocks:

```yaml
  e2e-tests:
    name: E2E Tests (${{ matrix.entrypoint }} / ${{ matrix.shard }})
    needs: ["files-changed", "pre-commit-hooks"]
    if: github.event_name == 'workflow_dispatch' || needs.files-changed.outputs.non_runtime_only != 'true'
    runs-on:
      group: huge-runners
    timeout-minutes: 40
    strategy:
      fail-fast: false
      matrix:
        entrypoint: [api, ui]
        shard: [readonly, mutation_small, mutation_large, ingress, backup, infrahub]
        exclude:
          # Shards that are entirely api_only (no UI surface to exercise)
          - { entrypoint: ui, shard: backup }
          # Add more exclusions here as the marker audit settles.
          # Each exclusion MUST be justified by every test in that shard
          # carrying @pytest.mark.api_only or @pytest.mark.ui_only.
    steps:
      - uses: actions/checkout@v6
      - uses: loft-sh/setup-vcluster@68e17a8c3618e3c47d635842b803d4f560f694e8
      - uses: azure/setup-helm@v4
      - uses: azure/setup-kubectl@v4
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.14"
      - name: Install uv
        uses: astral-sh/setup-uv@v7
      - run: uv sync
      - name: Install Playwright browser + system deps
        if: matrix.entrypoint == 'ui'
        run: |
          uv run playwright install chromium
          uv run playwright install-deps chromium
      - name: Build no-netlink shim
        if: matrix.entrypoint == 'ui'
        run: |
          apt-get update && apt-get install -y gcc
          gcc -shared -fPIC -Wall -Wextra \
            -o "$RUNNER_TEMP/no_netlink.so" \
            backend/tests/e2e/fixtures/no_netlink.c -ldl
          echo "NO_NETLINK_SO=$RUNNER_TEMP/no_netlink.so" >> "$GITHUB_ENV"
      - name: Install tini
        run: apt-get update && apt-get install -y tini
      - name: "Set environment variables"
        run: |
          RUNNER_NAME=$(echo "${{ runner.name }}" | grep -o 'ghrunner[0-9]\+' | sed 's/ghrunner\([0-9]\+\)/ghrunner_\1/')
          echo "VCLUSTER_DIR=/var/lib/github/${RUNNER_NAME}/_temp/.vcluster/config.json" >> $GITHUB_ENV
          # Per-shard image tag: avoids collisions when multiple matrix cells
          # run on the same self-hosted runner sequentially.
          echo "STYRMIN_IMAGE_VER=local-${{ runner.name }}-${{ github.sha }}-${{ matrix.shard }}-${{ matrix.entrypoint }}" >> $GITHUB_ENV
      - name: Enable E2E tracing
        if: inputs.enable-e2e-tracing == true
        run: |
          echo "OTEL_SERVICE_NAME=styrmin-e2e-${{ matrix.entrypoint }}-${{ matrix.shard }}" >> $GITHUB_ENV
          echo "OTEL_EXPORTER_OTLP_ENDPOINT=${{ secrets.TRACING_ENDPOINT }}" >> $GITHUB_ENV
          echo "OTEL_EXPORTER_OTLP_HEADERS=${{ secrets.OTEL_EXPORTER_OTLP_HEADERS }}" >> $GITHUB_ENV
          echo "OTEL_EXPORTER_OTLP_PROTOCOL=grpc" >> $GITHUB_ENV
          echo "OTEL_RESOURCE_ATTRIBUTES=github.run_id=${GITHUB_RUN_ID}" >> $GITHUB_ENV
          echo "PYTEST_OTEL_ARGS=--export-traces" >> $GITHUB_ENV
      - name: Run E2E tests
        run: |
          exec tini -s -g -- uv run pytest -v \
            -m "ci and shard_${{ matrix.shard }}" \
            -k "${{ matrix.entrypoint }}-chromium" \
            ${PYTEST_OTEL_ARGS:-} \
            backend/tests/e2e
      - name: Upload Playwright diagnostic artifacts
        if: failure() && matrix.entrypoint == 'ui'
        uses: actions/upload-artifact@v4
        with:
          name: playwright-test-results-${{ matrix.shard }}
          path: test-results/
          if-no-files-found: ignore
          retention-days: 7
```

**Verify before committing:**

- The `exclude:` block currently excludes only `(ui, backup)`. After Task 2's marker audit, also exclude `(ui, readonly)` and any other entrypoint/shard pair where every test carries `@pytest.mark.api_only`. Each exclusion is a runner saved.

- Sanity-check the matrix expansion locally: `gh workflow view ci.yml` — confirm 11 cells (12 minus the backup-ui exclusion) are listed.

- [ ] **Step 3: Update any downstream jobs that depended on the old job names**

```bash
grep -n "e2e-tests-api\|e2e-tests-ui" .github/workflows/*.yml
```

Update each reference (likely in `needs:` lists or PR status checks) to `e2e-tests`. If repo settings have required status checks pinned to `E2E Tests (API entrypoint)` / `E2E Tests (UI entrypoint)`, those need updating in GitHub settings — flag this in the PR description; the engineer can't do it from code.

- [ ] **Step 4: Push to a feature branch and trigger CI**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(e2e): shard E2E suite across 6 × 2 matrix jobs

Replaces the two monolithic e2e-tests-api / e2e-tests-ui jobs with
a matrix of (shard × entrypoint) cells. Each cell boots its own
vcluster and runs only the tests carrying its shard marker.

Refs: opsmill/styrmin#242"
git push -u origin HEAD
```

- [ ] **Step 5: Monitor the first matrix run and record per-shard wall-clock**

```bash
gh run watch
```

Expected: 12 cells (minus the `(ui, backup)` exclusion = 11 cells) all run in parallel. The longest one sets the new wall-clock floor.

If any cell goes red, the most likely causes are:

- **Cross-shard fixture coupling** — a test in shard X depended on state created by shard Y. Look for failing assertions about backup state, MinIO buckets, or BSL configuration. Fix by adding the missing setup to the shard-X tests, or by merging the shards.
- **Per-runner port collision** — multiple matrix cells on the same self-hosted runner racing on the same Docker network. The per-shard `STYRMIN_IMAGE_VER` prevents image collisions but not network collisions; if seen, add `--network` isolation per cell.
- **Shard imbalance** — one cell takes far longer than others. Note it; tune in a follow-up PR (re-split the shard).
- [ ] **Step 6: Record the before/after numbers**

In the PR description, paste:

```text
Before (last develop run, github.com/.../runs/<ID>):
  e2e-tests-api: XX min
  e2e-tests-ui:  YY min
  Total wall-clock (max): YY min

After (this PR, github.com/.../runs/<ID>):
  Slowest shard: ZZ min
  Reduction:     (YY - ZZ) / YY = NN%
```

---

## Task 8: Write `dev/guides/e2e-parallelism.md`

**Goal:** Phase 4a. The reference doc for "how does our matrix sharding work, and how do I add a new test?"

**Files:**

- Create: `dev/guides/e2e-parallelism.md`

- [ ] **Step 1: Write the guide**

Create `dev/guides/e2e-parallelism.md`:

```markdown
# E2E Parallelism: Matrix Sharding

## Overview

E2E tests run in a 6-shard × 2-entrypoint CI matrix. Each cell is a
GitHub Actions job that boots its own vcluster, installs styrmin via
Helm, and runs only the tests carrying its shard marker.

The six shards:

| Shard | Marker | Purpose | Sample tests |
|---|---|---|---|
| `readonly` | `shard_readonly` | Tests that only read shared state | `test_ui_smoke`, `test_service_discovery`, `test_admin_*` |
| `mutation_small` | `shard_mutation_small` | Short tests that create/delete their own deployment | `test_deploy_app`, `test_delete_deployment_*` |
| `mutation_large` | `shard_mutation_large` | Long mutation tests (parametrized or multi-stage) | `test_deployment_env_vars`, `test_environment_update`, `test_pod_scheduling` |
| `ingress` | `shard_ingress` | Ingress-controller scenarios (its own LB / IP allocation) | `test_ingress_controller` |
| `backup` | `shard_backup` | Velero + MinIO; cluster-wide state | `test_backup_restore*` |
| `infrahub` | `shard_infrahub` | The Infrahub app stack | (none yet) |

The two entrypoints (`api`, `ui`) continue as before — each shard runs
twice unless every test in it carries `@pytest.mark.api_only` or
`@pytest.mark.ui_only`. See `dev/guides/e2e-deployment-sharing.md` for
the marker rules.

## Adding a new test

1. Pick a shard using the decision tree in
   `dev/guides/e2e-deployment-sharing.md`.
2. Add module-scope markers to your file:

   \`\`\`python
   pytestmark = [
       pytest.mark.ci,
       pytest.mark.api_only(reason="..."), # or ui_only, or omit for dual
       pytest.mark.shard_readonly, # one of shard_readonly,

                                             # shard_mutation_small,

                                             # shard_mutation_large,

                                             # shard_ingress, shard_backup,

                                             # shard_infrahub

   ]
   \`\`\`

3. Run `uv run pytest --collect-only backend/tests/e2e -q` locally.
   The `enforce_shard_markers` hook in conftest will reject your test
   if the shard marker is missing or names an unknown shard.

## Debugging — `--pdb` still works

Matrix sharding does NOT change the per-test debugging recipe.
AGENTS.md's `--pdb` workflow continues to apply:

\`\`\`bash
sleep infinity | uv run pytest backend/tests/e2e/<node_id> -v -s --pdb 2>&1 | tee /tmp/pdb.log
\`\`\`

Each shard still runs single-threaded inside its CI job — no
pytest-xdist, no stdin trapping. The `e2e-troubleshoot` skill keeps
working without modification.

## Why matrix sharding (and not pytest-xdist)?

See ADR-00NN (e2e-matrix-sharding).

## Tuning a slow shard

If one shard becomes the wall-clock bottleneck (visible in the GitHub
Actions UI as the cell that takes longer than its siblings):

1. Identify the heaviest test(s) in that shard (`--durations=0` in the
   pytest output of that cell).
2. Either move the heaviest test to a new shard (update `pyproject.toml`
   marker list, conftest `_VALID_SHARDS`, CI matrix `shard:` list, and
   the test's `@pytest.mark.shard(...)`), or split the shard in half.
3. Re-run; confirm the new slowest cell is faster than the old one.
```

(In the actual file, use real triple-backticks.)

- [ ] **Step 2: Commit**

```bash
git add dev/guides/e2e-parallelism.md
git commit -m "docs(e2e): document the matrix-sharding parallelism scheme

Refs: opsmill/styrmin#242"
```

---

## Task 9: Update AGENTS.md and CONTEXT.md

**Goal:** Phase 4b + 4c. Point readers at the new guides and lock in the new vocabulary.

**Files:**

- Modify: `AGENTS.md` — the "Dual-entrypoint scope" and "Debugging E2E Tests" sections

- Modify: `CONTEXT.md`

- [ ] **Step 1: Find the "Dual-entrypoint scope" section in AGENTS.md**

```bash
grep -n "Dual-entrypoint scope\|Debugging E2E Tests" AGENTS.md
```

- [ ] **Step 2: Add a pointer to the new guides at the end of "Dual-entrypoint scope"**

Append this paragraph after the existing dual-entrypoint heuristic in AGENTS.md:

```markdown
**Shard markers (matrix CI):** Every `@pytest.mark.ci` E2E test ALSO
carries exactly one bare-name shard marker (`shard_readonly`,
`shard_mutation_small`, `shard_mutation_large`, `shard_ingress`,
`shard_backup`, or `shard_infrahub`) that routes it to one of six CI
matrix shards. See [`dev/guides/e2e-parallelism.md`](dev/guides/e2e-parallelism.md)
for the shard scheme and [`dev/guides/e2e-deployment-sharing.md`](dev/guides/e2e-deployment-sharing.md)
for the decision tree. The conftest hook `enforce_shard_markers` fails
collection if the marker is missing or duplicated.
```

- [ ] **Step 3: Confirm the "Debugging E2E Tests" section still describes a workflow that is true post-matrix**

The existing `--pdb` recipe runs against a single test node ID. Matrix sharding doesn't change this — each shard's CI job still runs single-threaded. Add a single sentence after the existing `--pdb` instructions:

```markdown
The matrix-sharded CI layout (one vcluster per shard) does not change
this recipe — each shard runs pytest single-threaded.
```

- [ ] **Step 4: Add "shard" and "test pod" entries to CONTEXT.md**

```bash
grep -n "^## \|^### " CONTEXT.md | head -20
```

Locate the glossary section (likely alphabetical). Add two entries:

```markdown
### Shard (CI E2E shard)

A subset of E2E tests routed together to one matrix cell of the
`e2e-tests` GitHub Actions job. Each shard boots its own vcluster.
Tests opt into a shard via a bare-name `@pytest.mark.shard_<name>`
marker. See [`dev/guides/e2e-parallelism.md`](dev/guides/e2e-parallelism.md).

The six shards: `readonly`, `mutation_small`, `mutation_large`,
`ingress`, `backup`, `infrahub`.

### Test pod

The set of tests that share one vcluster + styrmin install in CI —
operationally, one shard's worth of tests. Synonym for "shard
contents". Use "shard" when talking about the CI matrix cell; use
"test pod" when talking about the test grouping itself.
```

(Adjust the location to match CONTEXT.md's existing structure; do not
just paste at the bottom if the file is alphabetized.)

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md CONTEXT.md
git commit -m "docs(e2e): point AGENTS.md / CONTEXT.md at the new parallelism guides

Refs: opsmill/styrmin#242"
```

---

## Task 10: Write the ADR

**Goal:** Phase 4d. Record why we chose matrix sharding over pytest-xdist.

**Files:**

- Create: `dev/adr/00NN-e2e-matrix-sharding.md`

- [ ] **Step 1: Find the next ADR number**

```bash
ls dev/adr/ | grep -oE '^[0-9]+' | sort -n | tail -1
```

Take the next integer (e.g., if `0042` is highest, use `0043`).

- [ ] **Step 2: Write the ADR**

Create `dev/adr/0043-e2e-matrix-sharding.md` (with the real next number):

```markdown
# 0043. E2E test parallelism via matrix sharding (not pytest-xdist)

## Status

Accepted, 2026-05-23.

## Context

`backend/tests/e2e/` is the largest contributor to CI wall-clock. Pre-refactor
shape: two monolithic GitHub Actions jobs (`e2e-tests-api`,
`e2e-tests-ui`), each booting one vcluster and running every E2E test
serially in one worker. Target per issue #242: 30%+ wall-clock reduction
on the slower job while preserving the dual-entrypoint contract and the
`--pdb` debugging workflow described in AGENTS.md.

Two viable parallelism approaches:

- **Matrix sharding** — N CI jobs per entrypoint, each with its own
  vcluster. Selected.
- **pytest-xdist with worker-scoped vcluster** — one CI job, N workers
  on one runner each booting their own vcluster. Considered, rejected.

## Decision

Use **GitHub Actions matrix sharding** with 6 shards × 2 entrypoints
(minus exclusions for entirely api_only / ui_only shards). Each cell
boots its own vcluster.

Shards: `readonly`, `mutation_small`, `mutation_large`, `ingress`,
`backup`, `infrahub`. Routing via a bare-name `@pytest.mark.shard_<name>` marker
enforced by a conftest collection hook.

## Consequences

### Positive

- `--pdb` workflow unchanged — each shard runs single-threaded.
- Failure attribution is per-shard in the GitHub Actions UI.
- Tuning is YAML-level; re-sharding is a flat edit.
- The existing per-runner `STYRMIN_IMAGE_VER` mechanism already
  prevents cross-shard image collisions on shared self-hosted runners.
- Measured wall-clock reduction: NN% on the slower entrypoint
  (fill in after Task 7's CI run).

### Negative

- ~6× runner-minutes vs. the old 2-job layout. Acceptable on
  `huge-runners`; would not be acceptable on GitHub-hosted runners.
- Re-balance the shards when one becomes the bottleneck (see
  `dev/guides/e2e-parallelism.md`'s "Tuning a slow shard" section).
- Cross-shard fixture coupling now matters; tests cannot rely on
  state created by tests in other shards.

## Rejected alternative: pytest-xdist with worker-scoped vcluster

- Conftest rewrite would convert every `scope="session"` fixture to
  worker-scope, with care for `tmp_path_factory`, port-forward
  collisions, and Helm install collisions.
- 4+ vclusters on one runner = Docker / kubelet / inotify pressure.
  The existing `_portforward` retry loop already exists because of
  port allocation races; xdist multiplies the race surface.
- `--pdb` interaction: xdist traps stdin; AGENTS.md's debugging
  recipe would break unless we documented a "single-worker mode"
  toggle for every debugging session.
- Failure attribution: one interleaved log, N workers' worth of
  `_dump_namespace_logs` from N namespaces.

Reconsider only if matrix sharding hits a runner-cost ceiling.

## References

- Issue: opsmill/styrmin#242
- Spec: `docs/superpowers/specs/2026-05-23-e2e-parallelism-design.md`
- Plan: `docs/superpowers/plans/2026-05-23-e2e-parallelism.md`
- Guide: `dev/guides/e2e-parallelism.md`
- Guide: `dev/guides/e2e-deployment-sharing.md`
```

- [ ] **Step 3: Commit**

```bash
git add dev/adr/0043-e2e-matrix-sharding.md
git commit -m "docs(adr): record matrix-sharding choice for E2E parallelism

Refs: opsmill/styrmin#242"
```

---

## Task 11 (optional): GHA-API regression check script

**Goal:** Phase 4f, marked optional in the spec. A small script the CI can run to compare per-shard wall-clock against the previous green `develop` run.

Skip this task if Task 7's matrix output already makes drift obvious in the GH UI (it probably does — six green cells with their durations side-by-side is loud enough).

**Files:**

- Create: `tasks/check_e2e_regressions.py`

- [ ] **Step 1: Write the script**

Create `tasks/check_e2e_regressions.py`:

```python
"""Optional CI helper: warn if any e2e shard is >50% slower than last green develop.

Reads the GitHub Actions REST API via gh CLI, fetches the last
successful workflow run on develop, extracts per-job durations for
the e2e-tests matrix, and compares to the current run's durations.

Designed to print a GitHub Actions warning annotation (::warning::)
rather than fail the build — drift visibility, not enforcement.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


THRESHOLD = 1.50  # 50% slower → warn


def gh_json(args: list[str]) -> object:
    result = subprocess.run(
        ["gh", *args, "--jq", "."],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def get_current_run_id() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        msg = "GITHUB_RUN_ID env var required"
        raise RuntimeError(msg)
    return run_id


def jobs_for_run(run_id: str) -> list[dict]:
    data = gh_json(
        [
            "api",
            f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}/jobs",
        ]
    )
    return data["jobs"]  # type: ignore[index]


def e2e_durations(jobs: list[dict]) -> dict[str, float]:
    """Returns {shard-entrypoint-label: duration_seconds}."""
    out: dict[str, float] = {}
    for job in jobs:
        name = job["name"]
        if "E2E Tests" not in name:
            continue
        # name format: "E2E Tests (api / readonly)"
        started = job.get("started_at")
        completed = job.get("completed_at")
        if not (started and completed):
            continue
        from datetime import datetime

        dur = (
            datetime.fromisoformat(completed.replace("Z", "+00:00"))
            - datetime.fromisoformat(started.replace("Z", "+00:00"))
        ).total_seconds()
        out[name] = dur
    return out


def last_green_develop_run_id() -> str | None:
    data = gh_json(
        [
            "api",
            f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/workflows/ci.yml/runs?branch=develop&status=success&per_page=1",
        ]
    )
    runs = data["workflow_runs"]  # type: ignore[index]
    return str(runs[0]["id"]) if runs else None


def main() -> int:
    current = e2e_durations(jobs_for_run(get_current_run_id()))
    baseline_id = last_green_develop_run_id()
    if not baseline_id:
        print("No baseline run found on develop; skipping regression check.")
        return 0
    baseline = e2e_durations(jobs_for_run(baseline_id))
    for shard, cur_dur in current.items():
        base_dur = baseline.get(shard)
        if not base_dur:
            continue
        ratio = cur_dur / base_dur
        if ratio > THRESHOLD:
            print(
                f"::warning::E2E shard '{shard}' is {ratio:.0%} of "
                f"baseline ({cur_dur:.0f}s vs {base_dur:.0f}s)."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Wire it into the CI workflow as a post-step**

In `.github/workflows/ci.yml`, add a new job that depends on `e2e-tests`:

```yaml
  e2e-regression-check:
    name: E2E wall-clock regression check
    needs: ["e2e-tests"]
    if: always() && needs.e2e-tests.result == 'success'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Compare against last green develop
        env:
          GH_TOKEN: ${{ github.token }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          GITHUB_RUN_ID: ${{ github.run_id }}
        run: python tasks/check_e2e_regressions.py
```

- [ ] **Step 3: Commit**

```bash
git add tasks/check_e2e_regressions.py .github/workflows/ci.yml
git commit -m "ci(e2e): optional wall-clock regression annotation

Compares per-shard durations against the last green develop run and
emits a GH Actions warning if any shard slipped >50%. Visibility only,
not a blocker.

Refs: opsmill/styrmin#242"
```

---

## Final verification

- [ ] **Step 1: Full local collection sanity check**

```bash
uv run pytest --collect-only backend/tests/e2e -q 2>&1 | tail -5
```

Expected: `N tests collected in M.MMs`, no `PytestUsageError`.

- [ ] **Step 2: Per-shard collection check**

```bash
for shard in readonly mutation_small mutation_large ingress backup infrahub; do
  echo "=== $shard ==="
  uv run pytest --collect-only -m "ci and shard('$shard')" backend/tests/e2e -q 2>&1 | grep -E "^[0-9]+ test"
done
```

Expected: each shard collects ≥1 test (except possibly `infrahub` if no tests live there yet).

- [ ] **Step 3: Pre-commit + lint**

```bash
uv run invoke format lint
```

Expected: clean.

- [ ] **Step 4: Open the PR**

Use the `pr` skill or `gh pr create`. Body MUST include:

- Link to issue #242.
- Per-shard wall-clock numbers from Task 7's CI run.
- Before/after totals and the % reduction.
- Note about required-status-check rename: the old `E2E Tests (API entrypoint)` and `E2E Tests (UI entrypoint)` names are gone; if branch protection on `develop` requires them, update settings.

---

## Acceptance criteria (from #242)

- [ ] CI wall-clock for `e2e-tests-*` measurably lower on `develop` after the change lands; % drop stated in the merging PR using GitHub Actions job durations.
- [ ] All existing E2E scenarios still execute (no skips introduced); suite remains green on `develop`.
- [ ] `api_only` / `ui_only` markers correctly applied across the suite; no test runs `[ui-chromium]` when its actions never touch the UI.
- [ ] `dev/guides/e2e-parallelism.md` and `dev/guides/e2e-deployment-sharing.md` exist and AGENTS.md points to them.
- [ ] `--pdb` workflow per AGENTS.md confirmed unchanged (Task 9 Step 3).

---

## Notes on common pitfalls

- **Why bare-name shard markers, not `shard("name")`?** Pytest's `-m EXPR` mark expression evaluator filters on marker *names* only — it does not evaluate marker arguments. The parameterized form `@pytest.mark.shard("readonly")` is impossible to select with `-m`. Bare names (`@pytest.mark.shard_readonly`) are the only form that routes correctly in CI. The conftest guardrail (`enforce_shard_markers`) treats the six `shard_*` names as the canonical set.
- **Required status checks on `develop`:** Renaming the CI jobs from `e2e-tests-api` / `e2e-tests-ui` to a matrix `e2e-tests` likely breaks branch protection. Either keep the old job names as aliases (less clean) or update the branch protection settings in tandem with the merge.
- **vcluster setup cost:** Each shard pays the full vcluster + helm + image build cost (~3–6 min). If the slowest shard's *test* runtime is shorter than its setup cost, the floor is set by setup. Out-of-scope follow-up: pre-built image registry (Option C from the design discussion).
- **Cross-shard fixture coupling:** Velero / MinIO / BSL are created session-scope inside `styrmin_resources`. Each shard rebuilds them — fine. But if any test reads state created by a test in a different file in a different shard, it will break. The first CI run will surface this; fix by either merging shards or adding the missing setup.
