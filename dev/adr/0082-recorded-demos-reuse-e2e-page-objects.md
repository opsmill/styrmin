# ADR-082: Recorded Demos Act in the Styrmin UI Only Through the E2E Page Objects, and Recording Them Is Their Only Test

**Status**: Accepted
**Date**: 2026-10-21
**Decision-makers**: Fatih Acar
**Source**: specs/archive/031-recorded-feature-demos/research.md (R-006, R-012),
specs/archive/031-recorded-feature-demos/spec.md (Clarifications, sessions of 2026-10-17 and
2026-10-21; FR-003, FR-004, FR-014; SC-004); [issue #518](https://github.com/opsmill/styrmin/issues/518)
and its [PRD](https://github.com/opsmill/styrmin/issues/518#issuecomment-6240009049);
[PR #540](https://github.com/opsmill/styrmin/pull/540)
**Related**: [ADR-038](0038-scenario-driver-protocol-and-parametrized-fixture.md) (scenario driver
protocol), [ADR-083](0083-demo-waits-sped-up-after-recording.md) (how a demo becomes a video),
[ADR-084](0084-record-command-deletes-only-environments-it-created.md) (environments the command
deletes)

## Context

OpsMill shows four Styrmin features in the beta presentation: deploy and upgrade, component
overrides, environment backup and restore, and environment clone. Before this decision, a presenter
performed each feature in the Styrmin UI by hand, and a recording made by hand had to be made
again after each change to the UI (#518).

`uv run invoke record` records the four demos as videos. Each demo creates what it needs through
the SDK without recording it, then performs its feature in the Styrmin UI while Playwright records
the page. The E2E suite already performs Styrmin actions in the UI through the page objects under
`backend/tests/e2e/pages/` and `UiScenarioDriver`, and each action ends on a deterministic success
signal.

Two questions follow:

- Where the demo code lives, and how it reaches the Styrmin UI.
- How the demos are tested. Constitution §V asks for an E2E test of each new feature. A test that
  records the videos needs ffmpeg and a full Infrahub and Semaphore stack in CI, which is a CI
  workflow change that the PRD keeps out of scope.

## Decision drivers

- A fix for a change to a Styrmin page is made in one place, and it repairs both the E2E tests and
  the demos (SC-004).
- The E2E suite keeps filling fields in one step, while the videos show text typed one key at a time
  (FR-004).
- No CI workflow change and no Styrmin product change (FR-018).

## Considered options

For the location of the demos:

1. A package `backend/tests/e2e/demos/`, run as `python -m tests.e2e.demos` from `backend/`.
2. A top-level `demos/` directory.
3. A package `tasks/demos/`.

For typing one key at a time:

1. A keyword argument `keystroke_delay_ms` on each page object, set when the page object is created.
2. A module-level switch.
3. Typing in the demo scripts.

## Decision

The demos live in `backend/tests/e2e/demos/` (location option 1). The `record` task in
`tasks/demo.py` runs them as `python -m tests.e2e.demos` from `backend/`, the same way
`uv run invoke test` runs pytest from `backend/`, so the demos import `tests.e2e.pages` and
`tests.e2e.drivers` like the E2E suite does. pytest collects only `test_*.py`, so it does not collect
the demo modules. The unit tests of the demos live in `backend/tests/unit/demos/`, which the CI unit
job runs.

A demo performs every step in the Styrmin UI through `UiScenarioDriver` and the page objects, and
the demo scripts contain no selector for a Styrmin page (FR-003). When a demo needs a Styrmin action
that the page objects do not have, the action is added to the E2E page objects. The page objects for
Infrahub's and Semaphore's own web pages live in `backend/tests/e2e/demos/pages/`, because only the
demos use them (FR-014).

Typing follows typing option 1. Every page-object class that enters text, and `UiScenarioDriver`,
take a keyword-only `keystroke_delay_ms: int | None = None`, and a page object or driver that creates
another page object passes its value on. Page objects enter text with
`enter_text(locator, text, *, keystroke_delay_ms)` from `tests/e2e/pages/_dom.py`:

- With `None`, it calls `locator.fill(text)`. The E2E fixtures do not pass the argument, so the E2E
  suite fills fields in one step, as before.
- With a number, it clears the field with `fill("")` and types the text with
  `press_sequentially(text, delay=keystroke_delay_ms)`. The demos pass 45 ms.

The demos have no E2E test. This exception to Constitution §V was approved in the grilling session
of 2026-10-17. The proof of the feature was one run of the four demos on a demo stack that
`uv run invoke start` had just created, with the command output attached to PR #540. The review of
PR #540 (2026-10-21) added three rules:

- E2E tests call the Styrmin page-object methods that the demos added, on deployments that the tests
  already create. The `[ui-chromium]` variants of `test_override_then_clear` and
  `test_token_follows_upgrade_and_action_job` in `test_deployment_image_override.py` call the
  `DeploymentDetailPage` methods, and `test_pods_tab_copy_logs_command` in `test_ui_smoke.py` calls
  the `PodsTabPage` methods.
- The command has an owner, Fatih Acar.
- The demos are recorded again before each presentation that uses the videos, after a change to a
  UI page that a demo uses, and after a change to `infrahub_versions.yml`.

## Consequences

- Good, because a change to a Styrmin page that breaks a demo-added method fails an E2E test, and
  its fix in the page object repairs the demos too.
- Good, because the E2E suite does not change its typing: the default `None` keeps `fill()`.
- Good, because the demos import the page objects without changing `sys.path`. A top-level `demos/`
  or `tasks/demos/` would need `backend` on `sys.path` at run time, and `tasks/demos/` would make
  invoke import Playwright when it loads its tasks.
- Bad, because CI does not run the demos. A change that breaks a demo in another way shows only when
  someone records that demo.
- Bad, because the page objects for Infrahub and Semaphore have no test: a recording of demos 3 and
  4 is their only test. The owner and the schedule exist for that reason.
- Bad, because a field that reacts to each key, such as a combobox filter, can behave differently
  with `press_sequentially` than with `fill()`. The E2E suite does not exercise the typed path; each
  recording does.
- A new page-object class that enters text has to take `keystroke_delay_ms` and use `enter_text`,
  or the demos fill that field in one step (see the Testing section of
  [`dev/guidelines/backend/python.md`](../guidelines/backend/python.md#testing)).

A module-level switch (typing option 2) was rejected because it is global state that the E2E session
would share. Typing in the demo scripts (typing option 3) was rejected because it needs selectors in
the demo scripts, against FR-003.

## Confirmation

- The demo scripts in `backend/tests/e2e/demos/scenarios/` contain no selector for a Styrmin page.
- The three E2E tests named in the Decision call the demo-added methods and compare what they return
  with the API.
- The two places in `tests/e2e/conftest.py` that create `UiScenarioDriver` do not pass
  `keystroke_delay_ms`.

## More information

- [Recording the demos](../guides/local-demo.md#recording-the-demos) in the local demo guide: the
  command, the four demos, when to record them again.
- [Page objects shared with the recorded demos](../knowledge/backend/e2e-testing.md#page-objects-shared-with-the-recorded-demos)
  in the E2E knowledge page: the methods the demos added.
