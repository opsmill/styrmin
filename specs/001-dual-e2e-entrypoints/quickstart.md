# Quickstart — Dual-Entrypoint E2E Tests

This document is for an engineer running the dual-entrypoint E2E suite
locally for the first time, and for the author of a new scenario.

---

## Prerequisites

Same as the existing E2E suite, plus Playwright:

```bash
uv sync --all-groups --all-packages
uv run playwright install chromium
```

You also need the existing E2E prerequisites already documented for
`backend/tests/e2e/`: `docker`, `kubectl`, `helm`, `vcluster` CLI, a
reachable Docker daemon, and a `GITHUB_PAT` environment variable.

## Run the suite

| Mode                         | Command                                                                 |
| ---------------------------- | ----------------------------------------------------------------------- |
| Both entrypoints, all scenarios | `uv run pytest -m ci backend/tests/e2e`                              |
| API entrypoint only          | `uv run pytest -m ci -k "[api]" backend/tests/e2e`                      |
| UI entrypoint only           | `uv run pytest -m ci -k "[ui]" backend/tests/e2e`                       |
| One scenario, both entrypoints | `uv run pytest -m ci -k "test_deploy_simple_app" backend/tests/e2e`  |
| One scenario, one entrypoint | `uv run pytest -m ci -k "test_deploy_simple_app and [ui]" backend/tests/e2e` |

Each scenario appears twice in collection output — once as
`...[api]`, once as `...[ui]` — and that suffix is the single
selection axis used locally and in CI (research R7).

## Diagnose a UI failure

When a UI-entrypoint test fails, pytest-playwright writes three
artifacts per attempt under `test-results/`:

- `trace.zip` — open with `npx playwright show-trace trace.zip` for a
  step-by-step replay with DOM snapshots.
- `video.webm` — Chromium recording of the failing attempt.
- `test-failed-*.png` — screenshot at failure.

First-attempt artifacts are preserved even when the retry (FR-019)
succeeds, so flakiness is always observable — look under the attempt-1
subdirectory.

## Add a new scenario

1. Create the test function under `backend/tests/e2e/` as usual. Take
   `scenario_driver: ScenarioDriver` as a fixture argument **instead of**
   the `StyrminClient` directly.
2. Write the action steps against `scenario_driver.<action>(...)` and
   keep external-state assertions (kr8s, HTTP, kubectl) inline exactly
   as the API-only suite does today.
3. Run:
   ```bash
   uv run pytest -v backend/tests/e2e/test_<your_file>.py
   ```
   You should see two collected tests: `...[api]` and `...[ui]`.
4. If neither entrypoint can perform an action your scenario needs,
   stop and extend the weaker entrypoint first (FR-004 / FR-005). Do
   not reach for `@pytest.mark.api_only` / `ui_only` to paper over a
   gap — those markers are reserved for operations that are genuinely
   unreachable from the other side and require a recorded reason.

## Example: minimal dual scenario

```python
import pytest
from tests.e2e.drivers import ScenarioDriver
from tests.e2e.conftest import _wait_for_http


@pytest.mark.ci
async def test_deploy_simple_app(
    scenario_driver: ScenarioDriver,
    styrmin_resources: dict,
    simple_app_image: str,
    vcluster: dict,
) -> None:
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=styrmin_resources["environment_id"],
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id,
    )

    # External-state assertion — identical for both entrypoints.
    namespace = f"styrmin-{deployment.id}"
    ...  # kr8s port-forward + HTTP health probe as in the existing test
```

Collection shows:

```text
backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api]
backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[ui]
```

## Declare a single-entrypoint scenario

Only when an action is genuinely unreachable through the other
entrypoint (and that cannot be fixed in this feature):

```python
@pytest.mark.api_only(reason="ingress configured at cluster level; no UI surface today")
@pytest.mark.ci
async def test_ingress_controller(...): ...
```

The `[ui]` variant is still collected and reported — it skips with the
reason, not silently. Empty `reason` fails collection.
