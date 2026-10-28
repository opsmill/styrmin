# Implementation Plan: Check, Render and Compare an Application Driver on the Author's Machine with `styrmin-driver`

**Branch**: `032-styrmin-driver-cli` | **Date**: 2026-10-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/032-styrmin-driver-cli/spec.md`

## Summary

A driver author finds most errors in a driver only when a running Styrmin loads or deploys it, and an undefined template variable renders as an empty string with no message ([#23](https://github.com/opsmill/styrmin/issues/23)). This plan does two things:

- It moves the code that reads, checks and renders a driver directory, with the context model that templates read, from the backend to a new SDK package, `styrmin_sdk.driver_format`. The backend keeps every import path through re-export modules, so its behaviour does not change (research R-001, R-002).
- It adds the command `styrmin-driver` to the SDK, with four commands: `check`, `render`, `diff` and `context`. They build an example context with the server's own context function, render with a mode that reports every undefined variable with its line, and need no server, database, cluster or network (R-003 to R-010).

Two requirements of the brief would make three example drivers fail `check`; the plan changes FR-002 and FR-007 for them (spec, "Session 2026-10-28 (plan)").

## Technical Context

**Language/Version**: Python 3.14 in the workspace and in CI. The SDK keeps `requires-python = ">=3.12"`, with ruff checking its syntax for Python 3.12 (R-011).

**Primary Dependencies**: Jinja2 3.1.6, PyYAML 6.0.3, Pydantic 2.12.5 and packaging 25.0 in the SDK; `argparse` from the standard library for the command (R-010). The backend adds `styrmin-sdk`, a member of the workspace (R-017).

**Storage**: N/A. No database, Alembic revision or GraphQL schema change. The tool writes no file.

**Testing**: pytest. New unit tests in `python_sdk/tests/driver_format/`, with network access turned off by a fixture (R-014). The backend's existing driver, context and render tests run unchanged after the move. One new E2E node, `api_only`, on the session deployment of `simple-app` (R-013).

**Target Platform**: The author's machine (macOS or Linux, from a clone with `uv`), the Styrmin image (`python:3.14-slim`), and CI runners.

**Project Type**: Library and command-line tool (SDK), plus a refactor of the backend.

**Performance Goals**: From a clone, `check` and a first `render` finish in under one minute (SC-002). The commands read three small files and render one template.

**Constraints**:

- No server, database, cluster or network access (FR-013).
- The server's load and the agent's render keep their behaviour and their messages (FR-016).
- No module of `styrmin_sdk.driver_format` imports the backend, Prefect, dulwich, loguru, sqlmodel or the server settings (contracts/internal-interfaces.md).

**Scale/Scope**: About 5,000 lines move from the backend to the SDK, mostly without change. About 1,200 lines are new: the four commands, the example context, the check render and the diagnostics. About 35 backend modules become re-export modules (13 driver model files, 4 driver reading and checking modules, 10 context modules, 7 validator and helper modules, 1 renderer error module), and about 10 more change in part (`services/exceptions.py`, `services/env_vars/exceptions.py`, `services/utils.py`, `services/context.py`, `loaders.py`, `provider.py`, `application.py`, `agent/service/kubernetes/utils.py`, `server/app.py`, `cli/agent.py`). Seven documentation files and one changelog fragment change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative state reconciliation | Pass | No change to reconciliation. The tool reads files only. |
| II. Driver-based deployment | Pass | The driver format does not change. The tool checks drivers with the rules that the load applies. |
| III. Layered architecture | Pass | No GraphQL, service or repository layer change. The SDK package holds pure code that the backend's service layer and agent call, as they call it today. |
| IV. Type safety and typed errors | Pass | The moved errors keep `ServiceError` as their base, with their `error_code` and `error_metadata`, because the base class moves with them (R-002). Type hints stay; `ty` runs on the SDK. |
| V. Test-first development | Pass | Unit tests for each command and each check, the backend suite unchanged, and one E2E node that reuses `deployed_simple_app` ("Reuse before you boot"). Local PASS evidence is recorded for the E2E node. No GraphQL change, so no propagation test. |
| VI. Format and lint | Pass | `uv run invoke format lint` before each commit; the root ruff configuration lints `python_sdk/` for Python 3.12 (R-011). |
| VII. Documentation accuracy | Pass | User docs, reference page, ADR-0089, `dev/knowledge/architecture.md`, `python_sdk/AGENTS.md`, `CONTEXT.md` and changelog in the same change (R-019). |
| Governance gates | Ask first | New dependencies: `jinja2` and `packaging` in the SDK, `styrmin-sdk` in the backend; no new package expected in `uv.lock` (R-017). The brief records the decision to move the code to the SDK. No database, GraphQL, CI or authorization change. |

Post-design re-check: unchanged. The design adds no layer, no stored state and no network call.

## Project Structure

### Documentation (this feature)

```text
specs/032-styrmin-driver-cli/
├── spec.md
├── plan.md                         # This file
├── research.md                     # R-001 to R-020
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md                      # The command interface
│   └── internal-interfaces.md      # The SDK modules that the backend and the tool share
├── checklists/
│   └── requirements.md
└── tasks.md                        # Created by /speckit-tasks
```

### Source Code (repository root)

```text
python_sdk/
├── pyproject.toml                       # + jinja2, packaging; [project.scripts] styrmin-driver
├── src/styrmin_sdk/driver_format/
│   ├── __init__.py
│   ├── errors.py                        # ServiceError base and the moved errors (R-002)
│   ├── models/                          # driver model, moved from services/driver/models/
│   ├── context/                         # models/, resolvers, fqdn, validation/, naming, parameters,
│   │                                    # service_entries (R-001)
│   ├── reading/                         # parsers, deserializers, files, local (the local provider)
│   ├── checks.py                        # one function per check of the load (R-015)
│   ├── rendering.py                     # Jinja environment, filters, render_values(silent | check) (R-003, R-004)
│   ├── example_context.py               # build and merge (R-006 to R-008)
│   ├── diagnostics.py                   # Diagnostic, CheckReport, run_checks, YAML line mapping (R-005)
│   ├── diff.py                          # value comparison (R-009)
│   └── cli.py                           # argparse commands, main() (R-010)
└── tests/driver_format/
    ├── conftest.py                      # network blocked (R-014)
    ├── test_check_examples.py           # SC-001
    ├── test_check_errors.py             # one invalid driver per kind of error; SC-003 messages
    ├── test_rendering_check_mode.py     # R-003, R-004; output equals silent mode
    ├── test_example_context.py          # FR-002, FR-005, R-006, R-007
    ├── test_context_file.py             # FR-003, FR-004, R-008
    ├── test_diff.py                     # FR-011
    ├── test_cli_exit_codes.py           # FR-012, FR-017
    └── test_no_backend_imports.py       # contracts/internal-interfaces.md

backend/
├── pyproject.toml                       # + styrmin-sdk
└── styrmin_backend/
    ├── services/exceptions.py           # imports ServiceError and the moved errors from the SDK
    ├── services/driver/                 # models/, parsers, deserializers, validators become re-exports;
    │                                    # loaders.py and provider.py call the SDK; git provider, hash,
    │                                    # driver_directory, hooks, labels stay
    ├── context/                         # models/*, resolvers, validators, fqdn, exceptions become re-exports;
    │                                    # models/capabilities.py stays
    ├── services/{backup/ttl,env_vars/validator,container_overrides/validator,
    │             image_overrides/reference,replicas/exceptions,parameters/validator,utils}.py
    │                                    # re-exports of the moved names
    ├── services/context.py              # calls build_service_entries from the SDK
    ├── agent/service/kubernetes/resources/builders/application.py
    │                                    # render_value_template keeps @task, calls render_values(mode="silent")
    ├── agent/service/kubernetes/resources/builders/exceptions.py   # re-export
    ├── agent/service/kubernetes/utils.py                           # get_kubernetes_reference re-exported
    └── server/app.py, cli/agent.py      # forward the styrmin_sdk logger to loguru (R-012)

backend/tests/e2e/test_deploy_app.py     # + test_styrmin_driver_matches_helm_release (R-013)

docs/docs/drivers/creating-a-driver.md   # step 9
docs/docs/reference/styrmin-driver.md    # new
docs/docs/reference/index.md, docs/sidebars.ts
dev/adr/0089-driver-format-code-in-the-sdk.md
dev/knowledge/architecture.md
python_sdk/AGENTS.md
CONTEXT.md
changelog/23.added.md
```

**Structure Decision**: The tool lives in the SDK package of the existing workspace (`python_sdk/`), as the brief decided. The backend keeps its layout and import paths; its moved modules become re-export modules.

## Design

### Move to the SDK (R-001, R-002, R-011, R-012)

The move changes no behaviour, so the backend suite is its test:

1. Create `styrmin_sdk.driver_format` and move the modules of the R-001 table. Replace each moved backend module by a module that re-exports the same names.
2. Move `ServiceError` to `styrmin_sdk.driver_format.errors`; `services/exceptions.py` imports it.
3. Replace `config` in `models/structure/directory.py` and `loaders.py` by file-name parameters with today's defaults; the backend passes its settings.
4. Split `render_value_template`: the SDK's `render_values` holds the body; the backend's method keeps `@task` and calls it with `mode="silent"`.
5. Extract the service-entry loop of `services/context.py:238-273` into `build_service_entries`.
6. Replace loguru by the standard library in the moved code, and forward the `styrmin_sdk` logger to loguru in `server/app.py` and `cli/agent.py`.
7. Add `per-file-target-version = { "python_sdk/**/*.py" = "py312" }` to the root `[tool.ruff]` section.
8. Change test patch targets that pointed at an attribute of a moved module (R-002, "Risk").

### The check render (R-003, R-004)

`render_values(template, context, mode="check")` wraps the dump of the context in mappings that know their path and their model's field names, renders with the recording undefined, and returns the output and the list of undefined uses with their line and full name. A field of the model without a value renders as in silent mode. The prototype of both rules gave the agent's output and reported only the misspelled names.

### The example context and the context file (R-006, R-007, R-008)

`build_example_context` fills a `ContextInput` from the driver model as the server fills it from its records, with fixed IDs, an empty configuration and placeholder values for parameters without a default, and calls `resolve_global_context`. `merge_context_file` merges the author's file into the JSON dump of the example, sets the template text from the directory, and validates the result with `GlobalContext`.

### The checks and the diagnostics (R-005, R-015, R-016)

`run_checks` runs every check of the load's table and collects every problem: the per-field errors of the driver model with their YAML lines, the first template syntax error, every retired filter, the env var doc and backup checks, every missing action function, a syntax error of `actions.py`, and, when the model and the template syntax are valid, the undefined variables of the check render and a values text that is not YAML. The load warnings of `Info` become warnings.

### The command (R-009, R-010, R-018)

`cli.main` parses the arguments with `argparse` and calls one function per command. Usage errors exit with 2 from `argparse`; the command functions return 2 for an unreadable directory, context file or base file, and for a context that does not match the model. `render` and `context` write only their product to standard output; `check` writes its report there; `diff` writes the diff there. The streams and codes are those of [contracts/cli.md](contracts/cli.md).

### Delivery (R-020)

Two pull requests: the move first, with no user-visible change and the full backend and E2E suites as evidence; the tool second.

## Testing

| Requirement | Test |
|-------------|------|
| SC-001 | `test_check_examples.py`: `check` on each directory of `driver/examples/` exits with 0. |
| FR-001, SC-003 | `test_check_errors.py`: one driver per invalid case of the backend's driver tests (inventory from `backend/tests/unit/services/driver/`, groups A to D), each compared with the load's message after the wrapping prefix (R-015). |
| FR-002, FR-005, FR-006 (unit part) | `test_example_context.py`: `context` on `simple-app` holds its services; on `generic-app` a placeholder and a warning; the output validates against `GlobalContext`. |
| FR-003, FR-004 | `test_context_file.py`: one parameter changes only its values; lists replace; a mistyped key gives exit code 2 and the key. |
| FR-007, FR-008, FR-009 | `test_rendering_check_mode.py` and `test_check_errors.py`: line and full name; model fields without a value; unclosed `{% if %}`; all errors in one run; output equals silent mode for every example driver. |
| FR-010 | `test_check_errors.py`: invalid `spec.info.icon` gives a warning and 0. |
| FR-011 | `test_diff.py`: reordered keys give 0; `"8080"` to `8080` gives 1. |
| FR-012, FR-017 | `test_cli_exit_codes.py`: each code of each command; standard output of `render` on success and on failure. |
| FR-013 | `conftest.py` blocks sockets for every test of the tool. |
| FR-014 | E2E node, step 6 (`docker run` of the session image). |
| FR-015, FR-016 | The backend's existing tests (`uv run invoke test`) and the E2E suite pass without changes to expected messages; `test_no_backend_imports.py`. |
| SC-004, FR-006 | E2E node `test_styrmin_driver_matches_helm_release` (R-013). |

The E2E node's local pass is recorded with the evidence of constitution section V. Commands are in [quickstart.md](quickstart.md).

## Decisions for the reviewer

These choices were made by the plan, not by the brief. Each has a default that the plan uses:

1. **FR-007 narrowed**: a field of the context model without a value is not an error (R-004). Default: as written, because three example drivers depend on it.
2. **FR-002 extended**: placeholders for parameters without a default (R-006). Default: as written, because two example drivers depend on it.
3. **`argparse` instead of Cyclopts** (R-010). Default: `argparse`, to keep the SDK's dependencies to Jinja2 and packaging.
4. **Python 3.12 minimum kept, checked by ruff only** (R-011). Default: keep it; the publishing decision may change it.
5. **Standard-library logging in the SDK, forwarded to loguru** (R-012). Default: forward; fallback: add loguru to the SDK.
6. **Two pull requests** (R-020). Default: two.
7. **`check` accepts `--context`; `render` and `diff` skip the `actions.py` checks** ([contracts/cli.md](contracts/cli.md)). Default: as written.

## Complexity Tracking

No constitution violation. The size of the move (about 5,000 lines) is the cost of FR-015 (one copy of the rules); R-020 splits it into a pull request with no behaviour change, so its review is by its tests.
