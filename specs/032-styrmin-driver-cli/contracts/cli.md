# Contract: the `styrmin-driver` command

This is the interface that driver authors and CI use. The SDK package declares it as a console script ([research R-010](../research.md#r-010-command-framework-argparse-from-the-standard-library)). Every command reads files only, and needs no Styrmin server, database, cluster or network access (FR-013).

## Commands

```text
styrmin-driver check   <dir> [--context <file>]
styrmin-driver render  <dir> [--context <file>]
styrmin-driver diff    <dir> --base <file> [--context <file>]
styrmin-driver context <dir> [--context <file>]
styrmin-driver --help
styrmin-driver --version
```

- `<dir>` is a driver directory: the folder that holds `driver.styrmin.yml`, `values.j2.yml` and, when the driver declares actions, `actions.py`.
- `--context <file>` is a YAML or JSON file that holds only the values to change. The tool merges it into the example context ([R-008](../research.md#r-008-context-file-merge-and-validation)). JSON is accepted because it is valid YAML, so the `spec.context` of a `StyrminDeployment` can be passed as it is.
- `--base <file>` is a YAML file of Helm values, usually the saved output of an earlier `render`.
- `check` accepts `--context` so that an author can check a render with the values of a real deployment. The brief shows `--context` on `render` and `diff` only; this is an addition of the plan.

| Command | What it does | Standard output | Standard error |
|---------|--------------|-----------------|----------------|
| `check` | Runs the checks of a load from a local directory, then renders `values.j2.yml` when `driver.styrmin.yml` and the template syntax are valid (FR-001, FR-009). | The report: one line per error and warning, then one summary line. | Nothing, apart from an error that stops the command (exit code 2). |
| `render` | Runs the checks that the render needs (`driver.styrmin.yml`, template syntax, retired filters), renders `values.j2.yml`, and parses the result as YAML, as the agent does. It does not check `actions.py`, because the render does not use it. | The Helm values as YAML, and nothing else (FR-017). Nothing when the command fails. | Errors and warnings. |
| `diff` | Renders as `render` does, then compares the values with the base file (FR-011). | A unified diff when the values differ. Nothing when they are the same. | Errors and warnings. |
| `context` | Builds the example context, merges the context file when one is given, and checks the result against the context model (FR-002, FR-005). It exits with 1 only when `driver.styrmin.yml` has errors: an error of the template does not change the context. | The context as YAML, in the order of the context model. | Errors and warnings, such as the placeholder warning of [R-006](../research.md#r-006-placeholder-values-for-parameters-without-a-default). |

## Exit codes

| Code | Meaning | Examples |
|------|---------|----------|
| 0 | The driver passes, or the values are the same. Warnings do not change it (FR-010). | `check` with only a load warning on `spec.info.icon`; `diff` on a base file with reordered keys. |
| 1 | The driver has errors, or the values differ. | An undefined variable; a missing action function; a directory without `driver.styrmin.yml`; rendered output that is not valid YAML; `diff` with a change of type. |
| 2 | The command cannot run. | The directory does not exist or is not a directory; an unknown option or a missing argument; a context or base file that cannot be read, is not UTF-8 or is not valid YAML; a context file whose top level is not a mapping; a merged context that does not match the context model; an unexpected failure of the command itself (`styrmin-driver: internal error: <type>: <message>`). |

## Message format

Each error and warning is one line, in the format that editors and CI annotations read:

```text
<file>:<line>: error: <message>
<file>: error: <message>
<file>:<line>: warning: <message>
```

- `<file>` is the path of the file as the author gave the directory, for example `my-driver/values.j2.yml`.
- `<line>` is left out when the line is not known, for example for a missing `driver.styrmin.yml`.
- A message can take several lines, for example the load's message for a YAML syntax error. Only its first line starts with `<file>:<line>:`.
- `<message>` is the text of the load for the same problem (FR-001). The text of a load lists every invalid field of `driver.styrmin.yml` in one block; the tool writes each field on its own line, with the line of that field ([R-005](../research.md#r-005-line-numbers-for-errors-in-driverstyrminyml)).

Messages that only the tool writes, because the load has no equivalent:

| Problem | Line | Message |
|---------|------|---------|
| Undefined variable (FR-007) | The template line that uses it | `undefined variable 'parameters.admn_email'` |
| Context file key not in the context model (FR-004) | none | `context file <file>: <key path>: <pydantic message>`, for example `context file ctx.yml: parameters_typo: Extra inputs are not permitted` |
| Parameter without a default (R-006) | The line of the parameter in `driver.styrmin.yml` | `parameter 'image_repository' has no default; the example context uses the placeholder 'example-image_repository'` (warning) |
| No `default_version` (R-007) | The line of `spec.supported_versions` | `no default_version; the example context uses application version '0.1'; set app.version in a context file to change it` (warning) |

Summary line of `check`:

```text
<dir>: 2 errors, 1 warning
<dir>: no errors
```

## Example

```console
$ styrmin-driver check my-driver
my-driver/values.j2.yml:12: error: undefined variable 'parameters.admn_email'
my-driver/driver.styrmin.yml:41: error: Missing entrypoint for action upgrade: upgrade
my-driver: 2 errors, 0 warnings
$ echo $?
1

$ styrmin-driver render my-driver --context ctx.yml > values.yml
$ styrmin-driver diff my-driver --context ctx.yml --base values.yml
$ echo $?
0
```

The texts in this example show the format. The exact text of each load message comes from the shared code and is fixed by the tests of SC-003.
