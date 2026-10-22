---
title: Configuration
sidebar_position: 5
description: Server and agent configuration — environment variables, Helm values, defaults.
---

## Configuration

:::info Stub page — to be generated

This page will be generated from the Pydantic-settings models of the
server and the agent, and from the Helm chart's `values.schema.json`.
The text below describes the scope of the page, not its final content.

Until the generation step exists, these files define the settings:

- Server, agent and operator settings:
  [`backend/styrmin_backend/config.py`](https://github.com/opsmill/styrmin/blob/develop/backend/styrmin_backend/config.py)
- Helm chart values: the `values.yaml` files under
  [`helm/styrmin/`](https://github.com/opsmill/styrmin/tree/develop/helm/styrmin)
  and
  [`helm/agent/`](https://github.com/opsmill/styrmin/tree/develop/helm/agent)

:::

### Scope

The page will document every setting:

- **Server settings**: database URL, GraphQL options, Prefect
  connection, authentication, logging, feature flags. Defined in
  Pydantic-settings models, and set with environment variables or the
  Helm chart.
- **Agent settings**: server URL, poll intervals, status reporter
  interval, kopf operator options.
- **Helm chart values**: every value that the `styrmin` and `agent`
  charts accept, with defaults and validation rules.
- **Per-environment configuration**: the fields of `Environment.config`
  and `Cluster.config` that override defaults for one environment or
  cluster.

For each setting, the page will give the key name, the type, the
default, where you can set it (environment variable, Helm value, or
GraphQL field), and when to change it.

### Generation source

- **Schema**: the Pydantic-settings models of the server and the agent,
  and the Helm charts' `values.schema.json`
- **Build step**: not defined yet; it will write Markdown from the JSON
  schemas

### Related pages

- [Installation](../installation/index.mdx): the install guides that
  set these values for the first time.
- [Concepts and architecture → Architecture](../concepts-and-architecture/architecture.md):
  what the server and the agent do, which explains each setting.
