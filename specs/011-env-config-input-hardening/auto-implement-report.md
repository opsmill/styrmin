# Auto-Implement Report: 011-env-config-input-hardening

**Feature**: Env-Config Input Completeness + Validator Hardening + UI Test Infrastructure
**Spec dir**: `specs/011-env-config-input-hardening/`
**Base commit**: `535d711` (tasks: env-config input completeness + validator hardening (011))
**Head commit**: `5852c57` (chore(011): final-suite validation + FR cross-check (Phase 6 polish))
**Branch**: `011-env-config-input-hardening`

## Chunk-by-chunk ledger

| # | Phase | Tasks | ✅/⚠️/❌ | Commit |
|---|---|---|---|---|
| 1 | Phase 1+2 — Setup + US1 (input completeness) | T001..T006 (6) | 6/0/0 | `1cb1d38` |
| 2 | Phase 3 — US2 (frontend enum transform) | T007..T011 (5) | 5/0/0 | `c6886cf` |
| 3 | Phase 4 — US3 (validator typed error) | T012..T017 (6) | 6/0/0 | `8a6d9ea` |
| 4 | Phase 5 — US4 (UI E2E driver + marker audit) | T018..T024 (7) | 7/0/0 | `1e4a94b` |
| 5 | Phase 6 — Polish + FR cross-check | T025..T030 (6) | 5/1/0 | `5852c57` |

**Totals**: 30 tasks → 29 done, 1 deferred, 0 blocked. 5 implementation commits; +997/-198 lines across 20 files.

### Notable decisions flagged upward

- **Phase 3 (US2)**: The codegen produces TypeScript string-union types (`'HTTP' | 'HTTPS'`), not enum objects. Maps use the literals directly with `as const satisfies Record<string, ExternalUrlScheme>`. Helper extracted to `EnvironmentConfigurationTab.helpers.ts` to avoid `react-refresh/only-export-components` warnings — establishes a new project pattern.
- **Phase 3 (US2)**: The 009 H2 nested-clearing block was already structurally correct — `detectNestedOverridesBlock` only inspected `dedicated_ingress` / `scheduling`, never `ingress_class` / `db_size`. (Those fields would have been silently cleared without the H2 even noticing — the actual bug US1+US2 fix at source.) Only docstring updated.
- **Phase 4 (US3)**: No parallel guard added in `validate_env_vars_dict`; verified the per-entry path always reaches `validate_env_var_value`. `InvalidEnvVarValueError` mirrors `InvalidEnvVarNameError`'s positional-message + keyword-args constructor shape.
- **Phase 5 (US4)**: Data-model §4.3's claim "Pydantic Literal coercion produces SDK enum values" was wrong — `Literal["http","https"]` returns the string back. The api_driver therefore includes a manual SDK enum map mirroring the frontend's `transformEnumValue`. This map is captured in the api_driver's docstring as the parity counterpart to the frontend transform.
- **Phase 5 (US4)**: The frontend Tabs primitive renders plain `<button>` (no `role=tab`); page object uses `get_by_role("button", name="Configuration", exact=True)` rather than the `role=tab` selector mentioned in data-model §4.2.

## Tasks not completed

| Task | Status | Reason |
|---|---|---|
| **T029** | ⚠️ Deferred | Full E2E suite needs a live Kind/vCluster, not available in this auto-implement run. Per 008/009/010 precedent, deferred to PR opener. The unskipped T061 (`test_us4_environment_form_*`) and the marker-audited dual-entrypoint runs are the load-bearing checks that confirm US4 actually delivers — these must run before PR merge. |

## Review findings

Review pass run across the 5-commit diff (`535d711..HEAD`). **Zero HIGH findings.**

| Severity | File:line | Finding | Disposition |
|---|---|---|---|
| MEDIUM | `services/env_vars/validator.py:181-183` | `_extract_name_value` calls `str(item[1])` — silently coerces non-strings, bypassing `InvalidEnvVarValueError`. Currently no production caller, so dormant. | Deferred — file as follow-up. Plug when GraphQL `EnvVarInput` list path eventually routes through this helper. |
| MEDIUM | `tests/e2e/drivers/api_driver.py:290,296` | Closed-set enum map raises raw `KeyError` (not `ScenarioActionError`) if Pydantic gains a new `Literal` member without map update. | Deferred — cosmetic; failure mode is loud, just not typed. |
| MEDIUM | `tests/e2e/pages/environments.py:202-212` | `update_env_vars_via_form` always appends rows; api_driver merges (`{**existing, **new}`). If a test passes a key already in persisted config, ui_driver path → `DUPLICATE_ENV_VAR_NAME`; api_driver path → overwrite. T061 doesn't trip this today (fresh keys); latent parity bug. | Deferred — note in protocol docstring or fix in a follow-up. |
| LOW | `__tests__/EnvironmentConfigurationTab.test.tsx:32-34,82-84` | Render-test seed uses already-uppercase `"HTTPS"`/`"INGRESS"` enum strings; doesn't match the persisted-shape contract used elsewhere in the file. Cosmetic. | Deferred. |
| LOW | `api/errors.py:46` | New `INVALID_ENV_VAR_VALUE` is grouped under the 008 comment; should marker-comment it as 011. | Deferred. |

**Especially well done** (per reviewer): the schema-walking propagation test (T005) is the right shape and reusable; the api_driver's manual enum map carries clear closed-set justification; the validator unit tests parametrise non-string types comprehensively.

## Autonomous decisions (worth user revisit)

1. **Marker audit ratio missed SC-005 target.** Pre=9, post=7 (22% reduction vs ≥50% target). The 5 retained markers in `test_deployment_env_vars.py` cannot be removed because `UiScenarioDriver.update_deployment` is scheduling-only (no UI form for deployment-level env-vars). Reaching SC-005 would require frontend work clearly out of US4 scope. Each retained marker carries the AGENTS.md-required inline justification. Recommend explicitly noting this in the PR description so the reviewer doesn't expect the 50% number.
2. **T029 left `[ ]`** rather than ticked + deferred-with-note. Honest signal that the E2E suite has not actually run yet against a cluster.
3. **Three MEDIUM review findings deferred.** Per the auto-implement workflow rule (only HIGH+ block; MEDIUM/LOW recorded), all three were filed in this report and not patched inline. Each is small enough to fold into a follow-up PR or address in code review.

## Suggested next steps

1. **Run T029 against a live cluster** — `uv run pytest backend/tests/e2e/test_deployment_env_vars.py backend/tests/e2e/test_environment_update.py -v -s --pdb`. Required for "definition of done" per Constitution §V.
2. **Open a PR** (the 008→009→010→011 stack — coordinate merge order with predecessors). PR description should call out:
   - The four bug fixes (input completeness, frontend enum transform, validator typed error, UI E2E unskip).
   - SC-005 partial outcome (22% vs ≥50%) and why.
   - The three MEDIUM follow-ups recorded in this report, if you want them as PR-comment threads.
3. **(optional)** address the MEDIUM follow-ups inline before opening the PR if the reviewer prefers them landed than filed.
