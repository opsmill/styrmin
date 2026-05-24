---
title: Configuration
sidebar_position: 5
description: Server and agent configuration — environment variables, Helm values, defaults.
---

## Configuration

:::info Stub page — to be auto-generated

This page will be generated from the Pydantic-settings models (server
and agent) and the Helm chart's `values.schema.json`. The information
below is a placeholder describing scope, not the final content.

Until the auto-generation pipeline is wired up, the authoritative
sources are:

- Server settings:
  [`backend/styrmin_backend/config/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/config)
- Agent settings:
  [`backend/styrmin_backend/agent/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/agent)
- Helm chart values: the `values.yaml` files under
  [`helm/styrmin/`](https://github.com/opsmill/styrmin/tree/develop/helm/styrmin)
  and
  [`helm/agent/`](https://github.com/opsmill/styrmin/tree/develop/helm/agent)

:::

### Scope

This page will document every knob you can turn:

- **Server settings** — database URL, GraphQL options, Prefect
  connection, auth, logging, feature flags. Sourced from Pydantic-
  settings models, set via environment variables or the Helm chart.
- **Agent settings** — server URL, poll intervals, status reporter
  cadence, kopf operator options.
- **Helm chart values** — every value the `styrmin` and `agent`
  charts accept, with defaults and validation rules.
- **Per-environment configuration** — fields on `Environment.config`
  and `Cluster.config` that override defaults for a specific
  environment or cluster.

For each, the page will give: the key name, the type, the default,
where it can be set (env var / Helm value / GraphQL field), and
when you'd want to change it.

### Auto-generation source

- **Schema**: Pydantic-settings models (server + agent) and the Helm
  charts' `values.schema.json`
- **Build step**: TBD — emit Markdown from the JSON schemas

### Related

- [Installation](../installation/index.mdx) — the install guides that
  set these values for the first time.
- [Concepts and Architecture → Architecture](../concepts-and-architecture/architecture.md)
  — what the server and the agent actually do, so the knobs make
  sense in context.
