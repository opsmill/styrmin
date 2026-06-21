---
title: styrminctl CLI
sidebar_position: 3
description: Reference for every command, flag, and exit code in the styrminctl CLI.
---

## `styrminctl` CLI

:::info Stub page — to be auto-generated

This page will be generated from the Cyclopts command tree at build
time. The information below is a placeholder describing scope, not
the final content.

Until the auto-generation pipeline is wired up, the authoritative
source is the CLI itself:

```bash
styrminctl --help
styrminctl <command> --help
```

Plus the source tree under
[`cli/`](https://github.com/opsmill/styrmin/tree/develop/cli).

:::

### Scope

`styrminctl` is the Cyclopts-based command-line client for Styrmin.
It's a thin wrapper over the GraphQL API — it never talks to the
database or the agent directly.

This page will document, command by command:

- Top-level commands (`cluster`, `environment`, `deployment`,
  `driver`, `backup`, `restore`, `upgrade`, `auth`, ...)
- Sub-commands and their flags
- Output formats (`--output text|json|yaml`)
- Exit codes
- Authentication and configuration (where the CLI looks for a
  server URL and a token)

### Auto-generation source

- **Schema**: the Cyclopts command tree in
  [`cli/src/`](https://github.com/opsmill/styrmin/tree/develop/cli/src)
- **Build step**: TBD — walk the Cyclopts tree, emit one Markdown
  section per command, write it into this file

### `deployment apply` is idempotent

`styrminctl deployment apply -f <manifest>` is declarative: the CLI
sends the full desired state on every run and the **backend** decides
whether anything actually changed. Re-applying an unchanged manifest is
a clean no-op — no new application instance is created, no reconcile
task is dispatched, and the deployment's active instance and status are
left untouched. The command still exits successfully.

Each deployment in a run is reported with its outcome:

- `created <name>` — a new deployment was provisioned.
- `updated <name>` — the desired state differed and a reconcile was
  dispatched.
- `unchanged <name>` — the resolved desired state already matched the
  live state; nothing was done.
- `failed <name>` — the apply errored for that deployment.

A run ends with a summary line counting each outcome, for example:

```text
2 created, 1 updated, 3 unchanged, 0 failed
```

A run consisting solely of no-ops still exits with a success code, so
`apply` is safe to run repeatedly in a declarative loop.

:::note Re-applying a failed deployment

A no-op apply against a deployment in a terminal-failure state stays a
no-op — `apply` compares desired intent against current intent, not
health, so it will not retry a broken-but-unchanged deployment.
Recovering such a deployment is a separate refresh path.

:::

:::note Rebuilt image under an unchanged version

`apply` compares the *resolved desired state*, which is keyed on the
application version (and driver version), not on image content. An
application image rebuilt and re-pushed under the **same** version, with
unchanged config, resolves to an identical instance and is therefore a
no-op — `apply` will not redeploy it. Bump the version to force a
redeploy.

:::

### Manifest `spec.config` shape

`spec.config` accepts the same typed configuration whether `apply` creates
or updates a deployment. Environment variables — both deployment-scoped and
per-component — are written as a **list of `{name, value}` entries**, not as
a key/value map:

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-app
spec:
  driver: acme/my-driver
  version: "1.2.3"
  environment: production
  config:
    env_vars:
      - name: MY_ENV
        value: value01
    components:
      - name: server
        env_vars:
          - name: LOG_LEVEL
            value: debug
  parameters:
    replicas: 2
```

`spec.parameters` stays a `{name: value}` map.

### Related

- [Installation → Quickstart](../installation/quickstart.md) — the
  CLI's first appearance, plus authentication.
