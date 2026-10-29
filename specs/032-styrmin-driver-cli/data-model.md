# Data Model: `styrmin-driver`

The tool stores nothing: no database, no file it writes. The entities below exist in memory during one command. The models that already exist (the driver model `DriverSpec`, the context model `GlobalContext`) move to the SDK without changes to their fields ([research R-001](research.md#r-001-what-moves-to-the-sdk-and-under-which-package)).

## Driver directory

The folder that the author names on the command line.

| Field | Type | Rule |
|-------|------|------|
| `root` | path | Must exist and be a directory; otherwise exit code 2. |
| `spec_file` | file name | Default `driver.styrmin.yml`. Must exist; otherwise an error and exit code 1. The backend passes its setting (`STYRMIN_DRIVER_*`, `config.py:149-159`). |
| `values_template` | file name | Default `values.j2.yml`. Optional, as in the load: a missing file is an empty template. |
| `actions_code` | file name | Default `actions.py`. Read only when `spec.actions` is not empty. |

## Diagnostic

One problem or warning that a command found.

| Field | Type | Rule |
|-------|------|------|
| `severity` | `error` or `warning` | Any `error` gives exit code 1; warnings do not change the exit code (FR-010). |
| `file` | path | The file of the problem, as the author named the directory. |
| `line` | integer or none | Known for template errors, undefined variables, `actions.py` syntax errors, and `driver.styrmin.yml` fields ([R-005](research.md#r-005-line-numbers-for-errors-in-driverstyrminyml)). None for a missing file. |
| `message` | text | The load's message for the same problem, without the load's wrapping prefix ([R-015](research.md#r-015-several-errors-in-one-run-while-the-load-still-stops-at-the-first)), or one of the tool's own messages ([contracts/cli.md](contracts/cli.md#message-format)). |
| `check` | name | The check that found it: `spec-file`, `spec-model`, `env-var-docs`, `backup`, `template-syntax`, `retired-filter`, `actions-syntax`, `action-entrypoint`, `undefined-variable`, `values-yaml`, `load-warning`, `placeholder`, `version-placeholder`. Used by the tests to compare with the load (SC-003). |

Ordering: by file, then line, then the order in which the checks ran.

## Check report

The result of the checks on one driver directory.

| Field | Type | Rule |
|-------|------|------|
| `diagnostics` | list of diagnostics | The problems found in one run (FR-009). |
| `spec` | driver model or none | None when `driver.styrmin.yml` is missing, is not valid YAML, or does not match the driver model. |
| `template` | text | The text of `values.j2.yml`, or `""`. |
| `rendered` | Helm values or none | Present only when `spec` is present and the template syntax is valid, so the render ran (FR-009). |

Exit code of `check`: 1 when any diagnostic is an error, else 0.

## Example context

A `GlobalContext` built from the driver directory ([R-007](research.md#r-007-how-the-example-context-is-built)).

| Field | Rule |
|-------|------|
| `context` | Validates against `GlobalContext`. The same keys as the server's context for a new deployment with the default parameters, on a cluster and environment with no configuration. |
| `placeholders` | The parameters that received a placeholder ([R-006](research.md#r-006-placeholder-values-for-parameters-without-a-default)), each with its value. One warning each. |
| fixed identifiers | The deployment, environment, chart, repository and instance IDs are constants, so two runs give the same context. |

## Context file

The YAML or JSON file of `--context`.

| Field | Rule |
|-------|------|
| top level | A mapping; otherwise exit code 2. |
| keys | Any subset of the keys of the context. A mapping merges key by key into the example context; any other value, including a list, replaces it (FR-003). |
| `app.helm.chart.values_template` | Replaced by the text of the directory's template; a warning when the file set another value ([R-008](research.md#r-008-context-file-merge-and-validation)). |
| merged result | Must validate against `GlobalContext`; otherwise one error line per Pydantic error, naming the key path, and exit code 2 (FR-004). |

## Rendered values

The Helm values that `render` writes and `diff` compares.

| Field | Rule |
|-------|------|
| text | The template rendered with the merged context, in the strict mode of [R-003](research.md#r-003-one-render-reports-every-undefined-variable-with-its-line-and-its-full-name) and [R-004](research.md#r-004-a-field-of-the-context-model-without-a-value-is-not-an-error). |
| values | The text parsed with `yaml.safe_load`, as the agent parses it. Text that is not valid YAML is an error, exit code 1 ([R-018](research.md#r-018-render-writes-the-values-that-helm-receives)). |

## Base values file

The YAML file of `--base`.

| Field | Rule |
|-------|------|
| content | Parsed with `yaml.safe_load`. A file that cannot be read or parsed gives exit code 2. |
| comparison | Both sides written with `yaml.safe_dump(sort_keys=True)` and compared as text ([R-009](research.md#r-009-diff-compares-values)). Equal: exit code 0. Different: the unified diff and exit code 1. |

## Command outcome

| Outcome | Exit code | Standard output |
|---------|-----------|-----------------|
| Passed, or same values | 0 | The product of the command (report, values, context), or nothing for `diff`. |
| Driver errors, or values differ | 1 | The `check` report, the diff, or nothing for `render` and `context`. |
| Cannot run | 2 | Nothing. |
