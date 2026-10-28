---
title: styrmin-driver CLI
sidebar_position: 6
description: Reference for the styrmin-driver commands, which check, render and compare an application driver on your machine.
---

## `styrmin-driver` CLI

`styrmin-driver` checks, renders and compares an application driver on your
machine. It needs no Styrmin server, database, cluster or network access. It
applies the rules of a driver load from a local directory, with the code that
the server and the agent use, so a driver that passes `check` passes the
same checks when you load it.

### Run it

From a clone of the repository, after `uv sync`:

```shell
uv run styrmin-driver check driver/examples/simple-app
```

From the Styrmin image, which holds the example drivers in `/styrmin/drivers`.
The image is public, so pulling it needs no credentials:

```shell
docker run --rm registry.opsmill.io/opsmill/styrmin:<version> \
  styrmin-driver check /styrmin/drivers/simple-app
```

To check a driver of your own with the image, mount its directory:

```shell
docker run --rm -v "$PWD/my-driver:/work/my-driver:ro" \
  registry.opsmill.io/opsmill/styrmin:<version> \
  styrmin-driver check /work/my-driver
```

The image applies the rules of the Styrmin version in its tag.

### Commands

| Command | What it does | Standard output |
|---------|--------------|-----------------|
| `styrmin-driver check <dir> [--context <file>]` | Runs the checks of a load, then renders `values.j2.yml` with the example context. Reports every error and warning. | One entry per error and warning, then a summary line. |
| `styrmin-driver render <dir> [--context <file>]` | Renders `values.j2.yml` and parses the result as YAML, as the agent does. Does not check `actions.py`. | The Helm values as YAML, and nothing else. Nothing when the command fails. |
| `styrmin-driver diff <dir> --base <file> [--context <file>]` | Renders as `render` does and compares the values with a saved values file. | A unified diff when the values differ. Nothing when they are the same. |
| `styrmin-driver context <dir> [--context <file>]` | Builds the example context, merged with the context file when you give one. It exits with 1 only when `driver.styrmin.yml` has errors: it does not check `values.j2.yml`, whose problems do not change the context. | The context as YAML. |

`<dir>` is a driver directory: the folder that holds `driver.styrmin.yml`,
`values.j2.yml` and, when the driver declares actions, `actions.py`.
`render`, `diff` and `context` write errors and warnings to standard error.

### What `check` checks

- `driver.styrmin.yml` against the driver model: every invalid field, each on
  its own line.
- The documentation of environment variables and the backup configuration.
- The syntax of `values.j2.yml`, and the template filters that Styrmin removed.
- Each action of `spec.actions` whose function `actions.py` does not define,
  and a syntax error in `actions.py`. `check` reads `actions.py` without
  running it.
- The render of `values.j2.yml`, when `driver.styrmin.yml` and the template
  syntax are valid:
  - every use of an undefined variable, with its line;
  - an error while rendering, such as `{{ 1 + "a" }}`, with its line;
  - rendered text that is not valid YAML.
- A driver file that cannot be read, or is not UTF-8.

The messages are those of a load. A load stops at the first error; `check`
reports every error it finds in one run. Load warnings, such as a
`spec.info.icon` that is not an `https` URL, are warnings and do not change
the exit code.

#### Undefined variables

On the server, a variable that the context does not define renders as an
empty string, and nothing reports it. `check` and `render` report it as an
error, for example:

```text
my-driver/values.j2.yml:12: error: undefined variable 'parameters.admn_email'
```

- A variable is undefined when its name is neither a field of the context
  model nor a key of the context.
- A field of the context model without a value, such as
  `instance.config.fqdn_suffix` when no FQDN suffix is set, is not an error.
  It renders as on the server: an empty string that tests as false.
- An `is defined` test and the `default()` filter are allowed. They apply to
  the last name of a path: `parameters.x.y | default('z')` is an error when
  `parameters.x` is undefined.
- An `if` test on an undefined variable is an error, because the test would
  otherwise be false with no message.

### The example context

When you give no context file, the commands render with the example context:
the context that the server would build for a new deployment of the driver
with the default parameters, on a cluster and an environment with no
configuration. View it with `styrmin-driver context <dir>`.

- The parameters are their defaults. A parameter without a default gets a
  placeholder, and a warning names it:

  | Kind | Placeholder |
  |------|-------------|
  | `string` | `example-<parameter name>` |
  | `integer` | `0` |
  | `boolean` | `false` |
  | `enum` | the first of its `values` |

- The application version is `spec.default_version`. When the driver sets
  none, it is the version of the first `>=`, `==` or `~=` clause of
  `spec.supported_versions`, in the order the clauses are written, or
  `0.0.0`, and a warning says so.
- The components, the services and the Helm chart come from
  `driver.styrmin.yml`. The utilities are `ingress`, and `service-discovery`
  when the driver declares services.
- The deployment, environment, chart, repository and instance IDs are fixed,
  so two runs give the same values. The environment is named `example`.

The example context does not know your cluster's capabilities, your
environment's configuration, or the services of other deployments. Give them
in a context file when the template reads them.

### Context files

A context file is a YAML or JSON file that holds only the values to change:

```yaml
parameters:
  image_tag: "1.2.3"
instance:
  config:
    fqdn_suffix: apps.example.org
```

- A mapping merges into the example context key by key. Any other value,
  including a list, replaces the example's value.
- The result must match the context model. A key that the model does not
  have stops the command with exit code 2, and the error names the key.
- `app.helm.chart.values_template` is always the text of the directory's
  `values.j2.yml`.
- The `spec.context` of a `StyrminDeployment` is a full context in JSON. Pass
  it as it is to render the values of that deployment.

### `diff`

`diff` reads both sets of values as YAML and compares them as values. A
different key order, indentation or quoting is not a difference. A different
type is: `"8080"` and `8080` differ, because Helm receives a different value.

```shell
uv run styrmin-driver render my-driver > before.yml
# edit values.j2.yml
uv run styrmin-driver diff my-driver --base before.yml
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | The driver passes, or the values are the same. |
| 1 | The driver has errors, or the values differ. A directory without `driver.styrmin.yml` gives 1. |
| 2 | The command cannot run: the driver path does not exist or is not a directory, an option is unknown or missing, a context or base file cannot be read or is not UTF-8 or valid YAML, the merged context does not match the context model, or `styrmin-driver` itself fails (`styrmin-driver: internal error: ...`). |

With 2 separate from 1, CI can tell an invalid driver from a command that
could not run.

### Message format

```text
<file>:<line>: error: <message>
<file>: error: <message>
<file>:<line>: warning: <message>
```

The line is left out when it is not known. A message can take several lines,
for example the message of a YAML syntax error; only its first line starts
with `<file>:<line>:`. `check` ends with a summary line:
`<dir>: 2 errors, 1 warning`, `<dir>: 0 errors, 1 warning`, or
`<dir>: no errors`.
