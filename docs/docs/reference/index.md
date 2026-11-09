---
title: Reference
sidebar_position: 1
description: Reference for the StyrminDeployment custom resource, the styrminctl CLI, the driver specification, and Styrmin configuration.
---

## Reference

Look up schemas, fields, flags, and defaults. For how each component
works, see [Concepts and architecture](../concepts-and-architecture/index.md).

> **Status: in progress.** Most pages below are stubs. Each page will be
> generated from the source named in the table. Do not edit content
> that the generation step will overwrite.

### Reference pages

| Page | Content | Source |
|------|---------|--------|
| [`StyrminDeployment` CRD](./styrmindeployment.md) | Each field of the `StyrminDeployment` custom resource. | Generated from the OpenAPI schema embedded in the operator. |
| [`styrminctl` CLI](./styrminctl.md) | Each command, flag, and exit code of the `styrminctl` CLI. | Generated from the Cyclopts command tree at build time. |
| [`styrmin-driver` CLI](./styrmin-driver.md) | Each command, option, check and exit code of `styrmin-driver`, which checks and renders a driver on your machine. | Written by hand. |
| [Driver API](./driver-api.md) | Each field and action declaration of the `driver.styrmin.yml` specification. | Generated from the Pydantic models in `backend/styrmin_backend/driver/`. |
| [Configuration](./configuration.md) | Server and agent configuration: environment variables, Helm values, defaults. | Generated from the Pydantic-settings models and the Helm chart's `values.schema.json`. |

### How the pages will be generated

Each reference page will have a build step that generates its content
from a source file in the repository: the GraphQL schema, the Cyclopts
command tree, the Pydantic models, or a JSON schema. Until the
generation step exists, each stub describes its scope and links to the
code that defines it.
