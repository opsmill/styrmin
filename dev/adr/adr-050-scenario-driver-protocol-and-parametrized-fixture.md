# ADR-050: `ScenarioDriver` protocol with parametrized fixture — single scenario body, two entrypoints

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-dual-e2e-entrypoints/research.md (R1, with R4 and R7 supporting context)

## Context

The E2E suite needs to assert that every user-visible flow works through **both** the API entrypoint (Python SDK) and the UI entrypoint (frontend driven by Playwright). The naive approaches each fail in their own way:

- **Two test files per scenario** (`test_deploy_simple_app_api.py`, `test_deploy_simple_app_ui.py`) — duplicates the scenario body, drifts as one side gets fixed and the other doesn't, doubles maintenance.
- **One test file that drives both entrypoints in sequence within the same test** — couples the two entrypoints' state, makes test IDs ambiguous, and a failure on one side aborts the other.
- **Gherkin / pytest-bdd** — adds a parallel DSL the team would have to learn, fights pytest's async-first idiom.

The team also wanted a single selection axis (`-k`, marker, or otherwise) that works locally and in CI for all four useful filter modes: all variants, API only, UI only, single scenario both.

## Decision

Each scenario is a single `async def` pytest function in `backend/tests/e2e/`. The body issues actions through a `scenario_driver` fixture that satisfies a `ScenarioDriver` Protocol (deploy, upgrade, create backup, start/stop components, etc.). Two concrete drivers implement the protocol:

- `ApiScenarioDriver` — wraps `StyrminClient` from the SDK.
- `UiScenarioDriver` — wraps a Playwright `Page` plus page objects under `tests/e2e/pages/`.

A session-scoped `driver_mode` fixture is parametrized with `pytest.param("api", id="api")` and `pytest.param("ui", id="ui")`. The function-scoped `scenario_driver` fixture constructs the matching concrete driver and wires either the SDK client or the Playwright page through it. Every scenario therefore produces two test IDs by default — e.g. `test_deploy_simple_app[api-chromium]` and `test_deploy_simple_app[ui-chromium]`.

External-state assertions (kr8s service checks, HTTP probes against deployed apps, Kubernetes inspections) live **outside** the driver and stay shared — they are the same regardless of which entrypoint drove the deployment.

Opt-out is explicit. `@pytest.mark.api_only(reason=...)` and `@pytest.mark.ui_only(reason=...)` skip the non-matching variant with a visible reason string. The `api_only` audit discipline (in `e2e-testing.md`): a scenario calling **any** dual-entrypoint method on `scenario_driver` is by definition exercising both code paths and may not be marked `api_only` — that is the parity check.

`ScenarioDriver` methods return **driver-neutral ref dataclasses** (in `tests/e2e/drivers/refs.py`), not SDK models or Playwright Locators. The refs expose only the minimum surface scenarios need; anything beyond goes through a direct SDK lookup (`client.deployments.get(id).name`). This is the contract that keeps scenario bodies driver-agnostic.

**Selection axis** is uniform across local and CI: `pytest -k`. The four useful modes:

| Mode | Command |
|------|---------|
| Both variants | `uv run pytest -m ci backend/tests/e2e` |
| API only | `uv run pytest -m ci -k "[api]" backend/tests/e2e` |
| UI only | `uv run pytest -m ci -k "[ui]" backend/tests/e2e` |
| One scenario both | `uv run pytest -m ci -k "test_deploy_simple_app" backend/tests/e2e` |

CI runs the API and UI variants as **two separate jobs** (`e2e-tests-api`, `e2e-tests-ui`), each provisioning its own vCluster. Both are required for merge.

## Consequences

- One scenario body, two variants — no source duplication, no drift. Adding a new scenario covers both entrypoints by default.
- A new dual-entrypoint operation (creating a backup, starting components, …) is added to **both** `ApiScenarioDriver` and `UiScenarioDriver` so the protocol stays uniform. Adding a method to one driver but not the other forces `api_only` / `ui_only` on every test that uses it — a build-time signal that the UI flow is missing.
- Test IDs carry the entrypoint, so failures are immediately attributable (`test_deploy_simple_app[ui-chromium]` is unambiguous).
- The session-scoped underlying fixtures (`styrmin_resources`, vCluster) are shared between variants within a job, but `scenario_driver` itself is function-scoped to keep variants from leaking state between scenarios.
- Per-CI-cycle cost: each scenario runs ~2× (one variant per job). Acceptable because: (a) the variants run in parallel jobs, so wall-clock impact is ≤2×; (b) cluster bring-up dominates per-job time anyway; (c) the parity coverage is the whole point.
- Operations that are genuinely UI-only or API-only opt out explicitly via the marker with a recorded reason — a documented `api_only`/`ui_only` is the only acceptable form of single-entrypoint coverage; silent skips are forbidden.

## Alternatives Considered

- **Two separate test files per scenario** (`_api.py` / `_ui.py`): rejected. Duplicates the scenario body; makes "single source of truth" structurally impossible.
- **Subclassing a base TestCase with two subclasses per scenario**: rejected. pytest's class pattern conflicts with the async-first, fixture-driven style and bypasses `asyncio_mode = "auto"`.
- **Gherkin / pytest-bdd**: rejected. Adds a parallel text DSL to learn and a translation layer between feature files and the actual test code; the existing suite already reads as straight pytest.
- **Cross-check the API while running the UI variant** (e.g., assert via the SDK after a UI action): rejected. Leaks the API entrypoint into the UI run; defeats the purpose of "this scenario was actually executable through the UI alone".
- **`pytest-rerunfailures` UI-only auto-retry**: initially added with a `pytest_collection_modifyitems` hook marking every `[ui]` variant with `@pytest.mark.flaky(reruns=1)`; later **removed** in commit `bce37c1` because the plugin is incompatible with `--pdb` (the project's standard E2E debugging workflow). Do not reintroduce; documented in `AGENTS.md` § Debugging E2E Tests and `e2e-testing.md`.
- **Two pytest markers (`api_entry`/`ui_entry`) instead of `-k` on param IDs**: rejected. Adds a second selection axis the team has to remember and a second place to update when param IDs change.
- **Two CI jobs running back-to-back in one workflow**: rejected. Doubles wall-clock time and forfeits the cross-variant isolation the separate-jobs model provides.
