# Research: Check, Render and Compare an Application Driver on the Author's Machine with `styrmin-driver`

Code references are to `develop` at `8f450f6`. Paths without a prefix are under `backend/styrmin_backend/`. "Prototype" means a script run on 2026-10-28 with the repository's environment (Jinja2 3.1.6, pydantic 2.12.5, PyYAML 6.0.3, Cyclopts 4.10.1, ruff 0.15.9); the scripts are not part of the change.

## R-001: What moves to the SDK, and under which package

**Decision**: A new package `styrmin_sdk.driver_format` in `python_sdk/src/styrmin_sdk/driver_format/` holds the code that reads, checks and renders a driver directory, the context model that a template reads, and the command `styrmin-driver`. It holds:

| Part | Moves from | Notes |
|------|-----------|-------|
| Error base `ServiceError` and the errors that the moved code raises | `services/exceptions.py:8-19` (base), `services/driver/exceptions.py:8-39` (`DriverError` to `MissingDriverSpecificationError`), `services/exceptions.py:971-1050` (`RetiredTemplateFilter`, `retired_filter_load_message`, `RetiredTemplateFilterError`, the two migration guide URLs), `services/env_vars/exceptions.py` (`InvalidEnvVarNameError`, `DriverEnvVarDocComponentMismatchError`), the renderer errors `ChartValuesTemplateRenderingError` and `InvalidChartValuesError`, and the errors that the config validators of the context model raise | R-002 explains why the base moves. |
| Driver model | `services/driver/models/` (resources and structure) | `models/structure/directory.py` stops reading `config`: the three file names become parameters with today's defaults (`driver.styrmin.yml`, `values.j2.yml`, `actions.py`, `config.py:157-159`). The backend passes its settings, so `STYRMIN_DRIVER_*` overrides keep working (FR-016). |
| Reading and checks | `services/driver/parsers.py`, `deserializers.py`, `validators.py` (template syntax, retired filters, action entrypoints, env var docs, backup configuration), the reading part of `loaders.py`, and `LocalDriverProvider` from `provider.py` | `GitDriverProvider` stays in the backend with dulwich. `hash.py`, `driver_directory.py`, `hooks.py` and `labels.py` stay: the tool does not need them. |
| Template environment and render | `agent/service/kubernetes/resources/builders/application.py:74-177` (`split_string`, the retired filters, `get_jinja_environment`, `SilentUndefined`) and the body of `render_value_template` (`:222-285`) | The SDK function has no Prefect decorator. The backend method keeps `@task` and calls it (FR-016). |
| Context model | `context/models/contexts.py`, `config.py`, `components.py`, `helm.py`, `services.py`, `input.py`, and `context/resolvers.py`, `context/validators.py`, `context/fqdn.py`, `context/exceptions.py` | `context/models/capabilities.py` stays: `GlobalContext.cluster.capabilities` is `dict[str, Any]`, and only `services/capabilities.py` uses the model. |
| Validators that the context model calls when a field is set | `services/backup/ttl.py`, `services/env_vars/validator.py`, `services/container_overrides/validator.py`, `services/image_overrides/reference.py`, `services/replicas/exceptions.py` | `context/models/config.py` imports them inside its validators (lines 446, 520, 539, 594, 612, 621, 632, 705). In the SDK they are imported at module level where that does not create a cycle; the two cycles of today (`replicas/exceptions.py` and `container_overrides/__init__.py` importing the context models again) go away because the SDK modules do not import a resolver. |
| Helpers for the example context | `services/parameters/validator.py` (`parse_parameter_definitions`, `validate_parameter_values`), `services/utils.py:17-44` (chart name and repository from the chart URL), `agent/service/kubernetes/utils.py:5-8` (`get_kubernetes_reference`), and the loop that builds `services` and `deployed_services` in `services/context.py:238-273` | The loop becomes an SDK function that `generate_context_from_deployment` calls with the database rows, so the server and the example context build service entries with one copy of the code. |

**Size**: about 5,000 lines move: about 2,100 in `services/driver/` (part of it stays), about 2,400 in `context/`, about 780 in the five validators, and about 200 in the helpers. The moved code keeps its behaviour; only imports change.

**Name**: `styrmin_sdk.driver_format`, not `styrmin_sdk.driver`, because the SDK already has `styrmin_sdk.models.driver.ApplicationDriver` (`python_sdk/src/styrmin_sdk/models/driver.py:19`) and a `drivers` resource on the client. The backend dataclass `ApplicationDriver` (`services/driver/__init__.py:8`) stays in the backend.

**Rationale**: The tool needs the driver model, the checks, the renderer and the context model (FR-001, FR-004, FR-005). Each of them pulls the next one in: the driver model imports `ReplicaDeclaration` from `context/models/components.py` (`services/driver/models/resources/driver.py:87`), which imports `MAX_REPLICA_COUNT` and `SchedulingConfig` from `context/models/config.py` (`components.py:20`), whose validators import the five validator modules. A copy of any of these in the SDK would fall out of date, as `check_driver.py` does, so FR-015 requires a move.

None of the moved modules imports the database, sqlmodel, sqlalchemy, strawberry, kubernetes, kopf or Prefect. Their third-party imports are pydantic, pydantic_core, PyYAML, Jinja2, packaging and loguru (R-012 removes loguru).

**Alternatives considered**:

- Move only the driver model and the checks, and keep the context model in the backend. Rejected: the SDK cannot import the backend (the backend depends on the SDK, and the tool must run without the backend), and the driver model already needs `ReplicaDeclaration` from the context model.
- Copy the rules into the SDK. Rejected by the brief: the copy would fall out of date.
- Put the tool in `styrminctl`. Rejected by the brief: the glossary defines `styrminctl` as a thin client over the GraphQL API.

## R-002: The backend keeps its import paths through re-export modules, and one error base

**Decision**:

- Each moved backend module becomes a module that re-exports the SDK names under the same import path. For example, `context/models/contexts.py` becomes `from styrmin_sdk.driver_format.context.contexts import GlobalContext, ...` with an `__all__`. The backend's import sites do not change. The counts that this keeps stable: `context.models.contexts` is imported by 29 backend modules and 47 test modules, `context.models.config` by 25 and about 67, `services.driver.exceptions` by 6 and 17, `services.driver.loaders` by 1 and 13.
- `styrmin_backend.actions` keeps re-exporting `GlobalContext` (`actions/__init__.py:1-20`), so the `actions.py` files of drivers do not change (FR-016).
- The base class `ServiceError` moves to `styrmin_sdk.driver_format.errors`, and `services/exceptions.py` imports it from there. Every backend error keeps `ServiceError` as its base, and the moved errors keep their `error_code` and `error_metadata`.

**Rationale**:

- Re-export modules keep the class objects identical, so `isinstance` checks, Pydantic annotations on Prefect flows and `patch("styrmin_backend....")` targets that patch a name where it is used keep working.
- The GraphQL error extension sends a client the message and code only when `isinstance(original, ServiceError)` (`api/errors.py:69`); any other exception becomes "An internal error occurred" (`api/errors.py:94-100`). With one base class, the moved errors keep reaching clients as today.
- The class path of a moved class changes, for example `GlobalContext.__module__`. Nothing stores it: Prefect results are not persisted (no `persist_result` or result serializer in `backend/styrmin_backend`; `workflows/manager.py:214-259` set `cache_policy=NO_CACHE`), the database stores contexts as JSON (`db/models.py:532`), and the `StyrminDeployment` stores `model_dump(mode="json")` (`operator/crd/builder.py:81`).

**Risk**: a test that patches an attribute on a moved module itself, for example `patch("styrmin_backend.context.resolvers._resolve_scheduling_config")`, no longer reaches the code that the SDK calls. The implementation runs the whole backend test suite after the move and changes such targets to the SDK module. Not known: how many such patches exist.

**Alternatives considered**: a second error base in the SDK, with `api/errors.py` checking both. Rejected: every place that handles `ServiceError` would need the second base too, and missing one changes what a client receives.

## R-003: One render reports the undefined variables that it finds, with their line and full name

**Decision**: The tool renders with its own subclass of the agent's undefined class that records each use (amended below: it then fails where the agent's render fails). It records:

- the template line, found by walking the Python stack to the first frame whose globals hold `__jinja_template__` and calling `template.get_corresponding_lineno(frame.f_lineno)`. This is how Jinja maps its own tracebacks;
- the full name, such as `parameters.admn_email`. The tool keeps the path of each mapping of the context, and the undefined object reads the path of the mapping it was looked up in (amended below: the mappings are plain dicts, and their paths are in a table of the render).

Uses that are recorded: printing, `if` and other boolean tests, iteration, comparison, attribute access, and the operators that `jinja2.Undefined` routes to `_fail_with_undefined_error`. Uses that are not recorded: the `is defined` test and the `default()` filter, because both check `isinstance(value, Undefined)` without calling any of these methods.

**Evidence (prototype)**: a template with eight lines rendered once and reported `parameters.admn_email` on line 1, `parameters.bad key` on line 2, `services.web.portt` on line 3, `parameters.x` on line 5 and `parameters.mode` on line 6. It reported nothing for `is defined`, `default()`, `tojson` on a wrapped mapping, or `.items()` over a wrapped mapping, and the output of the defined values was unchanged.

**Rule that follows from Jinja**: `default()` and `is defined` guard only the last name of a path. `{{ parameters.x.y | default('ok') }}` reports `parameters.x` when `parameters.x` is undefined, as standard Jinja would fail on it.

**Implementation**: `render_values_checked(values_template, context) -> RenderResult` in `styrmin_sdk.driver_format.rendering`, next to `render_values`, which keeps its signature. A use of a name read on an undefined value is reported once, as its first missing name (`services.slurpit`, not also `services.slurpit.primary_fqdn`).

**Amended after the review of 2026-10-28**:

- `jinja2.Undefined` binds its operators (`+`, `[]`, calls, `<`, `int()` and others) to its own failure method when the class is defined (`jinja2/runtime.py`, class `Undefined`), so the override did not reach them. `_CheckingUndefined` binds them again: each records the use and the render goes on with an empty value. The agent's `SilentUndefined` keeps Jinja's behaviour, so an operation on an undefined value fails there. Replaced on 2026-10-29: each records the use, then fails as on the agent.
- An undefined value that Jinja makes itself, with a hint and no name (`loop.previtem` on the first item), is not a variable: it renders as on the agent.
- `render_values_checked` does not raise. `RenderResult.failure` gives the kind (`render`, `retired-filter`, `values-yaml`), the message and the template line, read from the traceback that Jinja rewrites (frames named `<template>`), for any exception. The undefined uses found before the failure are kept.

**Amended after the reviews of 2026-10-29**:

- The author of the brief chose that the check render renders as the agent's ([spec, clarifications of 2026-10-29](spec.md#session-2026-10-29-reviews-of-the-documentation-of-check)). Up to `3b406375`, the check render went on after a use that makes the agent's render fail, with a value of its own, and each review found cases where it then took another branch than the agent's render or hid an error that the agent's render reports. `_CheckingUndefined` now subclasses `SilentUndefined`: each of its methods records the use, then gives the agent's result or fails as the agent's render fails. A name read on it gives the agent's empty string, and the use is the undefined variable's.
- Many filters, tests and Python methods do not call the methods of the undefined value, such as `items`, `pprint`, `abs`, `is none` or `'abc'.startswith(x)`. `render_values_checked` wraps each filter and test of its environment, apart from `default`, `defined` and `undefined`, and uses a `Context` subclass whose `call` wraps each function and method call, apart from macros. Each wrapper records an undefined value passed to it, then calls the filter, test or function, whose result or failure is the agent's.
- An undefined list index or dict key (`s[x]`) is recorded once, as the key, and gives an undefined value, as on the agent. A key or a name read on a field without a value, on one of Jinja's own undefined values, or on an empty string, is not recorded. A name read on a string that is not empty is recorded as `<str>.name`.
- The undefined classes of the check render are named `SilentUndefined`, so that a message that names the class of a value is the agent's. The mappings are plain dicts, as on the agent. The state of the render (each mapping with its path and its known names, by `id`, and the uses) is in the context variable `_CHECK_RENDER`, which is set while the template is compiled and rendered. A template cannot read it, and the classes add no attribute whose name does not start with `__`. Jinja evaluates some constant expressions when it compiles, such as `"abc".nmae`; their uses are recorded with no line.
- Some uses do not read the value and are not recorded: `x in mapping`, which hashes it; `x in 'abc'`, which fails with the agent's `TypeError`; a name of `jinja2.Undefined` itself, such as `x._undefined_name`, or a name that starts with `__`; `{% if [x] %}`; `[x] | length`, where the list holds it; `mapping.get('x')`; and a slice bound (`[1, 2, 3][:x]`), because Jinja does not route a slice through `getitem` (`jinja2/compiler.py`, `visit_Getitem`). The render then fails with the agent's message.

**Rationale**: FR-009 asks for the undefined variables that the render finds in one run, with their line (FR-007). `jinja2.StrictUndefined` fails at the first use of any undefined variable, also one that the agent's render writes out as an empty string, and gives no line in the exception; the line is only in the traceback.

**Alternatives considered**:

- Find the names by walking the template AST (`jinja2.meta.find_undeclared_variables`). Rejected: it finds only top-level names and cannot tell which attribute of `parameters` is missing.
- Render once per error with `StrictUndefined`, removing each failing expression. Rejected: complex, and a template with N errors needs N renders.

## R-004: A field of the context model without a value is not an error

**Decision**: When a lookup misses a key, the tool checks whether the name is a field of the Pydantic model that the mapping comes from. If it is, the lookup returns an object that behaves as the agent's `SilentUndefined`: it renders as an empty string and tests as false, and nothing is recorded. If it is not, the lookup is an undefined variable (R-003). For a mapping that is not a model, such as `parameters`, `services`, `labels` or `cluster.capabilities`, the known names are the keys that the mapping holds.

The spec's FR-007 is changed to state this rule (spec, "Session 2026-10-28 (plan)").

**Rationale**: The agent renders `GlobalContext.model_dump(exclude_none=True)` (`application.py:266`), so every model field without a value is absent from the mapping. Three example templates read such fields:

- `generic-app/values.j2.yml:26`: `instance.config.fqdn_suffix` in an `if` expression;
- `infrahub/values.j2.yml:78-79` and `infrahub-enterprise/values.j2.yml:79-80`: `instance.config.external_url_scheme or "https"` and `instance.config.external_url_port`.

Under the brief's rule, `check` would report these three drivers, and SC-001 would fail. These templates are correct: the field exists, and the server renders it as empty.

**Evidence (prototype)**: a model with two optional fields set to `None`, and a template that prints one, tests it with `if`, uses it with `or "https"`, and also reads `instance.config.fqdn_sufix` and `parameters.helth_path`. The tool's output was identical to the output of the agent's `SilentUndefined` on `model_dump(exclude_none=True)`, and the tool reported only `instance.config.fqdn_sufix` (line 4) and `parameters.helth_path` (line 5).

**Consequence**: For a template without undefined variables, the tool's output equals the agent's output for the same context. The E2E test of SC-004 checks it on a cluster.

## R-005: Line numbers for errors in `driver.styrmin.yml`

**Decision**: The tool composes `driver.styrmin.yml` with `yaml.compose` (PyYAML), which keeps the start line of each node, and maps the location of each Pydantic error (`err["loc"]`, for example `("spec", "info", "authors")`) to the line of the deepest node on that path. When the path ends at a key that is missing, the line is the line of its parent mapping. The text of each line is the per-field line that the load already writes:

```text
The driver specification is invalid:
- spec.info.authors: Input should be a valid list (found 'fatih')
```

(`deserializers.py:37-45`; `backend/tests/unit/services/driver/test_driver_info.py:156`). The tool writes `driver.styrmin.yml:<line>: error: spec.info.authors: Input should be a valid list (found 'fatih')`.

For a missing action function, the line is the line of the action's `location` key in `spec.actions`. For a template syntax error and a retired filter, it is `TemplateSyntaxError.lineno` and the `lineno` that `retired_filter_load_message` already uses (`validators.py:76-81`).

**Rationale**: The spec requires the file and the line for each error (user story 1). The load gives the field path but not the line.

**Alternatives considered**: `ruamel.yaml`, which keeps line numbers on loaded data. Rejected: a new dependency; PyYAML's `compose` already gives the lines.

## R-006: Placeholder values for parameters without a default

**Decision**: For a parameter without a default, the example context holds a placeholder value of its kind, and the tool writes a warning that names the parameter and the placeholder:

| Kind | Placeholder |
|------|-------------|
| `string` | `example-<parameter name>` |
| `integer` | `0` |
| `boolean` | `false` |
| `enum` | the first entry of `values` |

The spec's FR-002 is changed to state this rule.

**Rationale**: `generic-app` declares `image_repository` without a default (`driver.styrmin.yml:32-34`, comment "no default => required") and uses it on `values.j2.yml:53`. `infrahub-mcp` declares `infrahub_address` without a default (`driver.styrmin.yml:29`) and uses it on `values.j2.yml:11`. The server's `validate_parameter_values` refuses a deployment that does not set a required parameter (`services/parameters/validator.py:29-93`), so a real context always holds a value. Without a placeholder, `check` would report both templates and SC-001 would fail.

**Alternatives considered**: report the missing value as an error, and ask the author to give a context file. Rejected: an example driver would then need a context file to pass `check`, and the template is correct.

## R-007: How the example context is built

**Amended after the review of 2026-10-28**: the example context is built, and the context file merged, whenever `driver.styrmin.yml` is valid, also when `values.j2.yml` has an error, so `context` works as the contract says. The fallback application version reads the clauses of `supported_versions` in the order they are written: `SpecifierSet` keeps them in a set whose order changes with the hash seed of the process.

**Decision**: The example context is the context that the server builds for a new deployment of the driver, with the default parameters, on a cluster and an environment that have no configuration. The tool builds it with the server's own function, `resolve_global_context` (`context/resolvers.py:641-714`, moved by R-001), from a `ContextInput` filled as the server fills it:

| Part | Value | Server source |
|------|-------|---------------|
| `app.name` | `metadata.name` of the driver | `services/context.py:199` uses the driver record's name. |
| `app.version` | `spec.default_version`; when it is absent, the version of the first `>=`, `==` or `~=` clause of `spec.supported_versions` (for example `0.1` for `>=0.1,<1.0`), or `0.0.0` when there is no such clause, with a warning that names the version and says to set `app.version` in a context file | `services/deployment.py:1861-1869` resolves `default_version` when no version is given. `supported_versions` is a version specifier, not a list (`services/driver/models/resources/driver.py:274`, `SpecifierSet` at `:331-337`). Only `semaphore` of the eight example drivers sets `default_version` (`semaphore/driver.styrmin.yml:9`). Not known: what the server does when neither is given; the fallback is this plan's choice. |
| `app.helm.chart` | `name` and `version` from `spec.helm.main`, `values_template` from the file, a placeholder `id` | `services/applications.py:338-355`, `services/utils.py:17-44` |
| `app.helm.repository` | `url` from `spec.helm.main.location`, a placeholder `id` | same |
| Components | `spec.components`, each with `enabled: true` | `services/applications.py:357-361`, `services/deployment.py:2042-2049` |
| `parameters` | defaults, and placeholders (R-006), through `validate_parameter_values` | `services/parameters/validator.py:29-93` |
| `cluster.config`, `environment.config`, `deployment.config` | `{}` | stored JSON (`services/context.py:188-192`) |
| `cluster.capabilities` | `{}` | stored columns (`services/context.py:230-231`); computed on the server from the cluster |
| `environment.name` | `example` | environment record |
| IDs (deployment, environment, chart, repository, instance) | fixed UUIDs, the same on every run, so that `diff` gives the same result each time | database |
| `instance.namespace`, `instance.release_reference` | `styrmin-<deployment id>` | `get_kubernetes_reference` (`services/context.py:182`, `:103-115`) |
| `labels` | `environment_id` and `deployment_id` | `services/context.py:218-221` |
| `utilities` | `ingress`, and `service-discovery` when the driver declares services | `DEFAULT_UTILITY_KINDS = [UtilityKind.INGRESS]` (`services/utilities/utilities.py:9`), `services/context.py:268-273` |
| `services`, `deployed_services` | one entry for each service of the driver, built by the function that R-001 extracts from `services/context.py:238-266` | same |

**Rationale**: FR-006 requires every key that a real context holds for the same driver. Building the example with the server's function gives the same keys. Leaving the configuration empty, instead of filling it with placeholders, keeps the example context free of keys that a real deployment may not have. So when an author merges a full real context into it (R-008), the result is the real context, and `render` gives the HelmRelease's values (SC-004).

**Not reproduced either**: the scheduling that a driver declares on a component. The server resolves it in `_populate_component_scheduling` (`services/context.py`), which stays in the backend because affinity references read the database. None of the eight example drivers declares component scheduling.

**What the example context cannot reproduce**: the cluster's capabilities, the environment's configuration and name, other deployments' services, and the real IDs. A template that uses them renders differently from a real deployment; the author gives a context file for them.

## R-008: Context file merge and validation

**Decision**:

1. The tool reads the context file with `yaml.safe_load`. JSON is valid YAML, so the `spec.context` of a `StyrminDeployment` can be passed as it is. A file that cannot be read or parsed, or whose top level is not a mapping, gives exit code 2.
2. It dumps the example context with `model_dump(mode="json", exclude_none=True)`, and merges the file into it: a mapping is merged key by key, recursively; any other value, including a list, replaces the example's value (FR-003).
3. It validates the result with `GlobalContext.model_validate`. A Pydantic error gives exit code 2, with one line per error that names the key path (`loc`) and the Pydantic message (FR-004).
4. It sets `app.helm.chart.values_template` to the text of `values.j2.yml`, because the tool renders the template of the directory. When the context file sets a different value, the tool writes a warning.

**Rationale**: The operator renders from `GlobalContext.model_validate(spec.context)` (`operator/pipeline.py:56-60`, `147-148`), and the context in the custom resource is `model_dump(mode="json", exclude_none=True)` (`operator/crd/builder.py:81`). Merging in JSON mode and validating gives the tool the same model that the operator renders from.

## R-009: `diff` compares values

**Decision**: `diff` loads the base file and the rendered values with `yaml.safe_load`, writes both with `yaml.safe_dump(sort_keys=True, default_flow_style=False)`, and compares the two texts with `difflib.unified_diff`. The headers are `--- <base file>` and `+++ rendered <dir>`. Equal texts give exit code 0 and no output; different texts give the diff on standard output and exit code 1.

**Rationale**: FR-011. Loading and writing both sides with the same library removes differences of key order, indentation and quoting, and keeps differences of type: `"8080"` loads as a string and `8080` as an integer, and `safe_dump` writes them as `'8080'` and `8080`.

## R-010: Command framework: `argparse` from the standard library

**Decision**: The command uses `argparse`, with one sub-parser for each command. The SDK declares it in `python_sdk/pyproject.toml`:

```toml
[project.scripts]
styrmin-driver = "styrmin_sdk.driver_format.cli:main"
```

`main()` returns the exit code. Each command is a function that takes the parsed arguments and returns 0, 1 or 2.

**Rationale**:

- `argparse` exits with 2 on an unknown option or a missing argument, which is what FR-012 requires.
- It adds no dependency to the SDK. The SDK is a library that the backend and every client import; Cyclopts would add Cyclopts and Rich to all of them.

**Evidence (prototype)**: Cyclopts 4.10.1 exits with 1 on an unknown option and on a missing argument. Calling the app with `exit_on_error=False` and catching `cyclopts.CycloptsError` gives 2, so Cyclopts would also work.

**Alternatives considered**: Cyclopts, as `styrminctl` uses (`cli/src/styrminctl/cli_commands.py:3-8`). Rejected for the reasons above. This is a choice for the reviewer to confirm.

## R-011: The SDK keeps Python 3.12 as its minimum, and ruff checks the syntax

**Decision**: `python_sdk/pyproject.toml` keeps `requires-python = ">=3.12"`. The root `[tool.ruff]` section gets `per-file-target-version = { "python_sdk/**/*.py" = "py312" }`, so `uv run invoke lint` rejects syntax that Python 3.12 cannot parse in the SDK.

**Amended during implementation**: the first design, a `[tool.ruff]` section in `python_sdk/pyproject.toml` with `extend = "../pyproject.toml"`, moved ruff's project root to `python_sdk/`, so ruff classed `styrmin_sdk` as a first-party package and reported 18 `I001` import-order findings in existing SDK tests. The per-file setting keeps one configuration root; with it, the SDK passes `ruff check` and a probe file with `except ValueError, TypeError:` under `python_sdk/` is reported as `invalid-syntax`.

**Evidence**:

- The modules that move (R-001) compile with CPython 3.12.14. The only module of the load path that does not, `agent/service/kubernetes/utils.py:22` (`except ValueError, TypeError, KeyError:`, PEP 758, Python 3.14), does not move; only `get_kubernetes_reference` from it moves.
- The moved code uses PEP 695 syntax once (`context/models/components.py:138`), which Python 3.12 supports.
- Ruff 0.15.9 with `--target-version py312` reports `invalid-syntax: Multiple exception types must be parenthesized on Python 3.12 (syntax was added in Python 3.14)` on such an `except` (prototype).

**Limits**: CI runs the SDK tests on Python 3.14 only (`.github/workflows/ci.yml:185-200`), and `uv.lock` resolves for `==3.14.*` only (`uv.lock:3`). Ruff checks syntax, not the standard library, so a call that exists only in Python 3.13 or later would not be found. Running the SDK tests on Python 3.12 would need a CI change, which is a governance gate; it is not part of this plan.

**Alternatives considered**: raise the minimum to Python 3.14, which is what CI tests. Rejected for now: the SDK is not published, and its minimum is part of the publishing decision that the brief leaves to Damien and Fatih. This is a choice for the reviewer to confirm.

## R-012: Logging in the moved code

**Decision**: The moved code logs with the standard library (`logging.getLogger(__name__)`) instead of loguru. The server and the agent forward the `styrmin_sdk` logger to loguru at start-up with an intercept handler, so the warnings that the moved code logs keep appearing in the server's log in its format.

**Evidence**: The moved modules make five loguru calls (`grep -c 'logger\.'` per file, minus one docstring mention at `services/env_vars/validator.py:70`): `context/models/components.py:118`, `services/backup/ttl.py:155` and `:167`, `services/env_vars/validator.py:76`, and one call in `context/resolvers.py`. The four that were read are warnings. The backend adds a loguru sink in `server/app.py:50` and configures the standard library in `cli/agent.py:38`. No intercept handler exists today. Without one, Python's last-resort handler still prints warnings to standard error, so no warning is lost, but its format changes.

**Rationale**: A library uses the standard library's logging and leaves the configuration to the program. Adding loguru to the SDK would make every SDK user depend on it.

**Alternatives considered**: add loguru to the SDK's dependencies (it is in `uv.lock` at 0.7.3). Simpler, and the log lines would not change. Rejected because of the rationale above; it remains the fallback if the forward proves fragile.

**Amended during implementation**: `styrmin_backend/__init__.py` installs the handler (`styrmin_backend/logging_bridge.py`) when the package is imported, instead of a call in each entry point. Backend tests capture these warnings with loguru sinks (`backend/tests/unit/services/env_vars/test_validator.py`, `backend/tests/unit/context/test_component_context_replicas.py`), and they pass unchanged this way. The handler sets `propagate = False` on the `styrmin_sdk` logger, so a root handler does not print the records a second time. Four of the five log calls used loguru's `{}` formatting with keyword arguments; they now use `%s` arguments that give the same text.

## R-013: E2E test on the session deployment of `simple-app`

**Decision**: One new test node, `test_styrmin_driver_matches_helm_release`, in `backend/tests/e2e/test_deploy_app.py`, marked `@pytest.mark.ci` and `@pytest.mark.api_only(reason=...)`. The module's `pytestmark = [pytest.mark.shard_general]` routes it to the `shard_general` shard (`test_deploy_app.py:20-22`). It uses the session fixture `deployed_simple_app` (`backend/tests/e2e/conftest.py:1283-1314`), which `test_deploy_simple_app` already uses, so no new deployment starts. The test:

1. reads the `StyrminDeployment` named after the namespace (group `styrmin.io`, version `v1alpha1`, plural `styrmindeployments`) with `CustomObjectsApi.get_namespaced_custom_object`, as `test_deployment_env_vars.py:414-426` does, and takes `spec.context`;
2. reads the HelmRelease of the namespace, as `test_task_steps.py:341-349` does, and takes `spec.values`;
3. writes the context to a file in `tmp_path` and runs `styrmin-driver render driver/examples/simple-app --context <file>` as a subprocess, from the test's environment (the clone);
4. checks that the rendered values equal `spec.values` (SC-004);
5. runs `styrmin-driver context driver/examples/simple-app` and checks that the example context has every key path of `spec.context` (FR-006);
6. runs `docker run --rm <image> styrmin-driver check /styrmin/drivers/simple-app` and checks exit code 0 (FR-014). The image is the one the session built: `f"{os.environ.get('STYRMIN_IMAGE_NAME', 'registry.opsmill.io/opsmill/styrmin')}:{os.environ.get('STYRMIN_IMAGE_VER', 'latest')}"`, as `docker-compose.yml:13` and `conftest.py:731-743` build it.

**Rationale**:

- The operator renders from `spec.context` (R-008), so equality with `spec.values` shows that the tool's render matches the operator's.
- The HelmRelease's values hold only the rendered template (spec, Clarifications).
- `api_only`: the test uses Kubernetes and subprocesses only; a `[ui-chromium]` variant would add about 20 minutes of CI time and no coverage (`AGENTS.md`, "Dual-entrypoint scope").
- Reuse before you boot: the deployment is read, not changed, and `test_deploy_simple_app` is an active consumer of the fixture (constitution, section V).
- The E2E job has Docker on the host, and the vcluster nodes use the host's images (`backend/tests/e2e/fixtures/styrmin-values.yaml:1-12`).

**Not known**: whether the deployment that the session fixture creates sets configuration that the example context does not have. It does not matter for SC-004, because the test passes the full context; it matters for FR-006 only if the session environment sets configuration, which adds keys to the real context that the example lacks. In that case FR-006's check compares only the key paths that do not come from cluster, environment or deployment configuration. The implementation records which case it is.

## R-014: Offline unit tests without a new dependency

**Decision**: `python_sdk/tests/driver_format/conftest.py` has an autouse fixture that replaces `socket.socket.connect`, `socket.socket.connect_ex` and `socket.create_connection` with a function that raises, for every test of the tool (FR-013). The command tests call `main([...])` in the same process and read the captured standard output, standard error and the returned exit code.

**Evidence**: no network-blocking plugin exists in the workspace: `pytest-socket` and similar packages are absent from `uv.lock` and every `pyproject.toml`.

**Alternatives considered**: `pytest-socket`. Rejected: a new dependency.

## R-015: Several errors in one run, while the load still stops at the first

**Amended after the reviews of 2026-10-29**: `check` runs each check that can run, but some checks stop at their first problem, and some problems stop other checks, so `check` can report more errors in one run than a load, not every error. FR-001, FR-007 and FR-009 of the [spec](spec.md#functional-requirements), as narrowed in its clarifications of 2026-10-29, replace the wording of this section.

**Decision**: The SDK exposes each check as a function. The functions that can find several problems return a list:

- `find_missing_entrypoints(code, actions)` returns every action whose function is missing;
- the Pydantic error of the driver model already lists every invalid field.

The backend's load keeps its order and raises the first problem with today's class and message. The tool's `check` calls every check, collects every problem and writes them all. The load's order and messages today:

| Step | Check | Error and message | Source |
|------|-------|-------------------|--------|
| 1 | Driver path | `DriverLoadingError`: "The driver path does not exist: {path}", "The driver path is not a directory: {path}" | `provider.py:256-259` |
| 2 | `driver.styrmin.yml` present | `MissingDriverSpecificationError`: "The driver specification file could not be found: {err}" | `loaders.py:182-187` |
| 3 | YAML syntax | `DriverLoadingError` from `ParsingError`: "Error while parsing the driver resource file: {err}" | `parsers.py:33-34`, `loaders.py:188-189` |
| 4 | Driver model | `DriverLoadingError`: "Error while deserializing the driver resource: The driver specification is invalid:\n- {path}: {msg} (found {value!r})" or "...: Provided data is not of expected type: {err}". `InvalidEnvVarNameError` passes through unwrapped. | `deserializers.py:22-57`, `loaders.py:200-205`, `services/env_vars/exceptions.py:33-39` |
| 5 | Template syntax | `DriverLoadingError`: "The driver resource validation failed: {jinja message}" | `validators.py:69-74`, `loaders.py:192-197` |
| 5 | Retired filter (first one found) | `RetiredTemplateFilterError`, unwrapped: "values.j2.yml line {lineno} calls the '{filter}' template filter, which was removed: ..." | `validators.py:76-81`, `services/exceptions.py:1016-1020` |
| 6 | Env var docs | `DriverEnvVarDocComponentMismatchError`, unwrapped | `validators.py:304-338`, `services/env_vars/exceptions.py:347-353` |
| 7 | Backup configuration | driver `ValidationError`, unwrapped: "Component '{name}': ..." (four messages) | `validators.py:163-293` |
| 8 | Action entrypoints, when `spec.actions` is not empty | `DriverLoadingError`: "The driver resource validation failed: Missing entrypoint for action {name}: {function}" | `validators.py:88-104`, `loaders.py:86-96`, `:195-197` |

The tool writes the message that the load would write for each problem, without the wrapping prefix ("Error while deserializing the driver resource: ", "The driver resource validation failed: "), because the tool's line already names the file. SC-003's tests compare the text after the prefix.

A missing `values.j2.yml` is accepted by the load (the template becomes `""`, `loaders.py:146-148`); the tool does the same.

## R-016: A broken `actions.py`

**Decision**: `check` reports a `SyntaxError` of `actions.py` as an error with its line (`SyntaxError.lineno`) and the Python message, does not report missing functions for that file, and exits with 1.

**Evidence**: `validators.py:89` calls `ast.parse` outside any `try`, and the load catches only the driver `ValidationError` (`loaders.py:192-197`). The `SyntaxError` passes up to the GraphQL extension, which returns "An internal error occurred" with code `INTERNAL_ERROR` (`api/errors.py:94-100`). No test covers it.

**Not changed**: the server's behaviour (FR-016). Wrapping the `SyntaxError` in a `DriverLoadingError` would give clients a useful message; it is a candidate follow-up issue.

## R-017: Dependencies and the lock file

**Decision**:

- The SDK gains two direct dependencies: `jinja2` (the renderer and the template checks) and `packaging` (`services/driver/models/resources/driver.py:70-71`, version specifiers). Both are already in `uv.lock`: `jinja2` 3.1.6 (`uv.lock:1102-1103`) and `packaging` 25.0 (`uv.lock:1634-1635`).
- The backend gains `styrmin-sdk`, a member of the same workspace.
- No new package is expected in `uv.lock`. The implementation runs `uv lock --check` and compares the lock file with `develop`.

**Difference from the brief**: the brief lists Jinja2 only. The driver model also needs `packaging`.

**Dependency scan**: the change adds dependencies to manifests, so the Trivy filesystem scan of the PR checklist applies, comparing the PR branch with `develop`.

## R-018: `render` writes the values that Helm receives

**Decision**: `render` parses the rendered text with `yaml.safe_load`, as the agent does (`application.py:280-285`), and writes the result with `yaml.safe_dump(sort_keys=False)`. Rendered text that is not valid YAML is an error ("The chart values are not valid YAML: ..."), with exit code 1.

**Rationale**: The HelmRelease's `spec.values` is the parsed result, so the author views what Helm receives: comments and Jinja whitespace are gone, and types are visible. `diff` compares the same parsed values (R-009).

**Alternatives considered**: write the raw rendered text. Rejected: two templates that give the same values could print differently, and a YAML error would show only when the driver is deployed.

## R-019: Documentation, ADR and glossary

**Decision**: the changes listed in the spec's "Documentation" section, with these paths:

- `docs/docs/drivers/creating-a-driver.md`, step 9: `check` and `render` before the load.
- `docs/docs/reference/styrmin-driver.md`, a new page written by hand, as `styrminctl.md` is; added to `docs/sidebars.ts` (category `Reference`, `sidebars.ts:53-62`) and to the table of `docs/docs/reference/index.md:19-24`.
- `dev/adr/0089-driver-format-code-in-the-sdk.md`: the backend depends on the SDK, which holds the driver format code and the context model (R-001, R-002, R-012). The last ADR today is `0088`.
- `dev/knowledge/architecture.md`, for the new place of the driver format code.
- `python_sdk/AGENTS.md`: the new package and its role.
- `CONTEXT.md`: the entries **Driver CLI / styrmin-driver** and **Example context**, and the sentence added to **SDK / styrmin-sdk**, in the wording of the brief, with FR-007's rule on fields without a value.
- `changelog/23.added.md`: a towncrier fragment of type `added` (`pyproject.toml:327`).

## R-020: Delivery in two pull requests

**Decision**: The change ships in two pull requests on the same branch line:

1. **Move**: `styrmin_sdk.driver_format` with the moved code (R-001), the re-export modules (R-002), the logging forward (R-012), the ruff target (R-011) and the ADR. No user-visible change. The whole backend test suite and the E2E suite pass without changes to expected messages (FR-015, FR-016).
2. **Tool**: the four commands, the example context, the strict render, the unit tests, the E2E test, the documentation, the glossary and the changelog.

**Rationale**: The move touches about 5,000 lines and many import sites, and the tool adds new behaviour. A reviewer can check the first pull request by its tests alone, because it must change no behaviour, and review the second for the tool only.

**Alternatives considered**: one pull request. Possible, but a reviewer would have to tell moved lines from new ones in one diff. This is a choice for the reviewer to confirm.
