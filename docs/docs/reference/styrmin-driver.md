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

The image applies the rules of the Styrmin version in its tag. Images of
Styrmin 0.1.55 and earlier do not have the command. `styrmin-driver --version`
prints the version of the SDK package, not the Styrmin release.

`styrmin-driver` renders `values.j2.yml` with Jinja as the agent does,
without a sandbox, so a template can run Python code on the machine that
runs the command. Run it on drivers you trust, or in an isolated job, for
example for a pull request from a fork.

### Commands

| Command | What it does | Standard output |
|---------|--------------|-----------------|
| `styrmin-driver check <dir> [--context <file>]` | Runs the checks of a load and renders `values.j2.yml` with the example context. Reports the errors and warnings it finds; some errors hide others (see [What `check` checks](#what-check-checks)). | One entry per error and warning, then a summary line. |
| `styrmin-driver render <dir> [--context <file>]` | Renders `values.j2.yml` and parses the result as YAML, as the agent does. Does not check `actions.py`. | The Helm values as YAML, and nothing else. Nothing when the command fails. |
| `styrmin-driver diff <dir> --base <file> [--context <file>]` | Renders as `render` does and compares the values with a saved values file. | A unified diff when the values differ. Nothing when they are the same. |
| `styrmin-driver context <dir> [--context <file>]` | Builds the example context, merged with the context file when you give one. It exits with 1 only when `driver.styrmin.yml` has errors: it does not check `values.j2.yml`, whose problems do not change the context. | The context as YAML. |

`<dir>` is a driver directory: the folder that holds `driver.styrmin.yml`,
`values.j2.yml` and, when the driver declares actions, `actions.py`.
`render`, `diff` and `context` write errors and warnings to standard error.

### What `check` checks

`check` runs the checks of a load from a local directory, then renders
`values.j2.yml` once:

- `driver.styrmin.yml` against the driver model, and the checks across its
  fields: the environment variables documented in `spec.env_vars`, and the
  `backup` block of each component;
- the syntax of `values.j2.yml`, and the template filters that Styrmin
  removed;
- when `spec.actions` declares actions, the syntax of `actions.py` and the
  functions that the actions name. `check` reads `actions.py` without
  running it, so it does not report an import that fails, and a load does
  not either;
- each file that it reads: the file must be readable and UTF-8;
- when `driver.styrmin.yml` matches the driver model and the template syntax
  is valid, the render of `values.j2.yml` with the example context, merged
  with your context file when you give one with `--context` (see
  [Context files](#context-files)): undefined variables, errors while
  rendering, and rendered text that is not valid YAML.

A load stops at the first check that fails. `check` can report more errors
in one run, but some errors hide others. For example:

- an error in `driver.styrmin.yml` can stop other checks of that file. A
  YAML syntax error in it also stops the checks of `actions.py`, and a YAML
  syntax error or an error against the driver model stops the render;
- a syntax error in `values.j2.yml` or in `actions.py` stops the other
  checks of that file;
- the render stops where the server's render fails, for example at
  `{{ 1 + "a" }}`, at `{{ parameters.x + 1 }}` when `parameters.x` is
  undefined, or at a removed filter. The variables after that point are not
  checked.

Fix what `check` reports and run it again, until it reports no error.

The render takes only some branches of the template. A variable used only in
a branch that the render does not take is not checked, and `check` does not
warn about it: for example in an `{% if %}` that is false, in the
`{% else %}` of an `{% if %}` that is true, in a `{% for %}` over an empty
list, or in a macro that the template never calls. To check that branch,
give a context file that makes the render take it. `render` and `diff` have
the same limit.

Most messages are those of a load. `check` also writes messages of its own,
for example for an undefined variable or for a file that is not UTF-8. When
`spec.actions` declares actions and `actions.py` is missing, a load from a
local directory fails and a load from a Git repository accepts the driver;
`check` reports the missing file. Add `actions.py`, or remove `spec.actions`.

Load warnings, such as a `spec.info.icon` that is not an `https` URL, are
warnings and do not change the exit code.

#### Undefined variables

On the server, a variable that the context does not define gives no error
with a line. What it gives depends on how the template uses it:

- written out, it renders as an empty string;
- some filters and tests give a value with no error, for example `0` for
  `| length`, `Undefined` for `| pprint`, and false for `is none`;
- other uses make the render fail with a message that gives no line: for
  example, `{{ parameters.admn_email + 1 }}` fails with
  `'dict object' has no attribute 'admn_email'`, and
  `{{ parameters.admn_email | abs }}` with a `TypeError`.

`check` and `render` render the template with the server's undefined values,
which also record their uses, and report each use that they record as an
error, with its line, for example:

```text
my-driver/values.j2.yml:12: error: undefined variable 'parameters.admn_email'
```

- A variable is undefined when its name is neither a field of the context
  model nor a key of the context.
- A field of the context model without a value, such as
  `instance.config.fqdn_suffix` when no FQDN suffix is set, is not an error.
  It renders as on the server: an empty string that tests as false.
- A use is recorded when the template writes the variable out, tests it in
  an `if`, loops over it, compares it, uses it in an operation, reads a name
  or an item of it, or passes it to a filter, a test, a function or a
  method. A name read on an undefined variable, such as `parameters.x.y`, is
  reported as the variable, `parameters.x`.
- Where the server's render fails, the render fails too, with the server's
  message and the line, for example at `{{ parameters.x + 1 }}` or at
  `{{ parameters.x | abs }}`. The uses after that point are not checked in
  that run.
- Some uses are not recorded, for example `parameters.x in parameters`,
  `{% if [parameters.x] %}`, `[parameters.x] | length` and
  `parameters.get('x')`. A slice bound such as `[1, 2, 3][:parameters.x]` is
  not recorded either: the render fails there with the server's message, at
  its line.
- The `default()` filter and the `is defined` and `is undefined` tests are
  allowed. They apply to the last name of a path:
  `parameters.x.y | default('z')` is an error when `parameters.x` is
  undefined.
- A variable stored with `{% set %}`, or passed to a macro, is reported at
  the line that uses it.

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
- The `config` of `cluster`, `environment` and `deployment` is merged into
  `instance.config`, as on the server. The service entries are then built
  again with the FQDN suffix of the result, unless the file sets `services`.
- The warnings about a value that the example context makes up are left out
  when the file sets that value.
- The result must match the context model. A key that the model does not
  have stops the command with exit code 2, and the error names the key.
- The keys of `parameters`, `labels`, `services` and `capabilities` are not
  checked: a misspelt parameter name, or a value of the wrong kind, is
  accepted.
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
