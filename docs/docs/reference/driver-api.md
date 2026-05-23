---
title: Driver API
sidebar_position: 4
description: Reference for the driver.styrmin.yml specification — every field, every action declaration, every context primitive.
---

## Driver API

:::info Stub page — to be auto-generated

This page will be generated from the Pydantic models that validate
`driver.styrmin.yml` and the action declarations. The information
below is a placeholder describing scope, not the final content.

Until the auto-generation pipeline is wired up, the authoritative
sources are:

- [`backend/styrmin_backend/driver/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/driver)
  — the Pydantic models for the driver specification.
- [`driver/DRIVERS.md`](https://github.com/opsmill/styrmin/blob/develop/driver/DRIVERS.md)
  — the human-written description of the driver format.

:::

### Scope

This page will document the `driver.styrmin.yml` specification field
by field:

- `apiVersion`, `kind`, `metadata`
- `spec.version` — Application Driver Version
- `spec.supported_versions` — semver specifier for the Application
  Versions this driver supports
- `spec.info` — description, authors
- `spec.helm.main` — Helm chart reference (location, version, values
  template)
- `spec.components` — component definitions (label selectors,
  defaults)
- `spec.parameters` — typed user-facing inputs
- `spec.services` — declared network endpoints
- `spec.actions` — lifecycle action declarations (hook, mode, Python
  function, prompts)

It will also document the **action primitives** drivers can call from
their Python actions (`stop_component`, `start_component`,
`execute_commands`, `upgrade_deployment_version`, ...).

### Auto-generation source

- **Schema**: the Pydantic models in
  [`backend/styrmin_backend/driver/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/driver)
- **Build step**: TBD — emit Markdown from Pydantic JSON schemas
  with field descriptions sourced from the model docstrings

### Related

- [Drivers → Creating a driver](../drivers/creating-a-driver.md) —
  the task-oriented walkthrough.
- [Drivers → The Context](../drivers/context.md) — the runtime data
  structure every action and template sees.
- [Concepts and Architecture → What is an Application Driver?](../concepts-and-architecture/what-is-a-driver.md)
  — the conceptual page.
