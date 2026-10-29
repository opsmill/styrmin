# Contract: the SDK modules that the backend and the tool share

The backend's load, the agent's render and `styrmin-driver` call the same functions ([research R-001](../research.md#r-001-what-moves-to-the-sdk-and-under-which-package), FR-015). This page lists the modules of `styrmin_sdk.driver_format`, what each one gives, and who calls it. Function names are the plan's; the implementation may change a name if it updates this page.

## Modules

| Module | Gives | Moved from | Called by |
|--------|-------|------------|-----------|
| `errors` | `ServiceError` (the base of every backend error), the driver errors (`DriverError` to `MissingDriverSpecificationError`), `RetiredTemplateFilterError` and its helpers, `InvalidEnvVarNameError`, `DriverEnvVarDocComponentMismatchError`, `ChartValuesTemplateRenderingError` and `InvalidChartValuesError` of the renderer, and the errors of the context validators | `services/exceptions.py`, `services/driver/exceptions.py`, `services/env_vars/exceptions.py`, `agent/service/kubernetes/resources/builders/exceptions.py` | backend (re-export), tool |
| `models` | The driver model (`DriverSpec`, `Specification`, parameters, services, actions, backup, env var docs, `Info` with its warnings) and the directory layout with its three file names | `services/driver/models/` | backend (re-export), tool |
| `context` (package) | `context.models` (`GlobalContext` and its sub-models, `ContextInput`), `resolve_global_context`, `context.fqdn`, `context.validation` (the config validators and their exception modules), `context.naming` (`get_kubernetes_reference`, the chart URL helpers), `context.parameters` (`validate_parameter_values`), and `context.service_entries` (`build_service_entries`) | `context/`, the five validator modules, `services/parameters/validator.py`, `services/utils.py`, `agent/service/kubernetes/utils.py`, `services/context.py:238-273` | backend (re-export, and `generate_context_from_deployment` calls `build_service_entries`), tool |
| `reading` (package) | `reading.parsers` and `reading.deserializers` (moved whole), `reading.files` (`ResourceFileLoader`, `get_resource_file_loader`), `reading.local` (`DriverProvider`, `LocalDriverProvider`) | `services/driver/parsers.py`, `deserializers.py`, `loaders.py:154-243`, `provider.py:29` and `:247` | backend loader and `GitDriverProvider`, tool |
| `checks` | One function per check of the load's table ([R-015](../research.md#r-015-several-errors-in-one-run-while-the-load-still-stops-at-the-first)): `check_template_syntax`, `find_retired_filters`, `check_env_var_docs`, `check_backup_configs`, `find_missing_entrypoints`. The functions that can find several problems return a list. | `services/driver/validators.py` | backend loader (raises the first problem), tool (collects all) |
| `rendering` | `get_jinja_environment`, `SilentUndefined`, `render_values(template, context)`, and `render_values_checked(template, context) -> RenderResult` for the tool | `agent/.../builders/application.py:74-285` | agent (`render_value_template` keeps its Prefect `@task` and calls `render_values`), `utilities/ingress.py`, tool (`render_values_checked`) |
| `example_context` | `build_example_context(directory, spec) -> (GlobalContext, placeholders)`, `merge_context_file(example, data) -> GlobalContext` | new | tool |
| `diagnostics` | `Diagnostic`, `CheckReport`, `run_checks(directory, context=None) -> CheckReport`, the line mapping of [R-005](../research.md#r-005-line-numbers-for-errors-in-driverstyrminyml) | new | tool |
| `cli` | `main(argv=None) -> int`, the console script `styrmin-driver` | new | console script |

## Rules

- **Behaviour of the backend does not change** (FR-016):
  - the load raises the first problem, with today's exception class and message;
  - `render_values` gives today's output for every template, including undefined variables rendered as empty strings;
  - `STYRMIN_DRIVER_*` settings still choose the file names, because the backend passes them to `models` and `reading`.
- **`render_values_checked`** records undefined variables ([R-003](../research.md#r-003-one-render-reports-every-undefined-variable-with-its-line-and-its-full-name)), treats a context model field without a value as the agent does ([R-004](../research.md#r-004-a-field-of-the-context-model-without-a-value-is-not-an-error)), and returns the output with the undefined variables. It does not raise: `RenderResult.failure` says why a render produced no values, with the template line. For a template without undefined variables, its values equal those of `render_values`.
- **Two classes per renderer error name**: `ChartValuesTemplateRenderingError` and `InvalidChartValuesError` exist twice today: as plain `Exception` subclasses in `agent/service/kubernetes/resources/builders/exceptions.py:1-5`, which the renderer raises, and as `ServiceError` subclasses in `services/exceptions.py:121-128`. Only the renderer's pair moves, and it keeps `Exception` as its base. The `ServiceError` pair stays in the backend.
- **Import paths**: every moved backend module keeps its path as a module that re-exports the SDK names ([R-002](../research.md#r-002-the-backend-keeps-its-import-paths-through-re-export-modules-and-one-error-base)). `styrmin_backend.actions.GlobalContext` keeps working.
- **No backend import in the SDK**: no module of `styrmin_sdk.driver_format` imports `styrmin_backend`, Prefect, dulwich, loguru, sqlmodel or the server settings. A unit test imports `styrmin_sdk.driver_format` in a subprocess and checks that none of these is in `sys.modules`.
- **Python 3.12 syntax**: `python_sdk/` is linted for Python 3.12 through `per-file-target-version` in the root ruff configuration ([R-011](../research.md#r-011-the-sdk-keeps-python-312-as-its-minimum-and-ruff-checks-the-syntax)).
- **Logging**: the SDK logs with `logging.getLogger("styrmin_sdk....")`; the backend forwards that logger to loguru ([R-012](../research.md#r-012-logging-in-the-moved-code)).
