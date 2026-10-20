---
title: Reference
sidebar_position: 1
description: Lookup pages for Styrmin's primary surfaces — the StyrminDeployment CRD, the styrminctl CLI, the Driver API, and Styrmin configuration.
---

## Reference

This section is for **lookup**: schemas, fields, flags, defaults. It's
not for learning — if you want to understand how a piece works, head
to [Concepts and Architecture](../concepts-and-architecture/index.md).

> **Status: in progress.** The pages below are currently stubs while
> the auto-generation pipeline is being set up. Each notes which
> upstream source the final content will be generated from so
> contributors don't try to hand-write content the tooling will
> overwrite.

### What's in here

| Page | What it covers | Source |
|------|----------------|--------|
| [`StyrminDeployment` CRD](./styrmindeployment.md) | Field-by-field reference of the `StyrminDeployment` Kubernetes Custom Resource. | Generated from the OpenAPI schema embedded in the operator. |
| [`styrminctl` CLI](./styrminctl.md) | Every command, flag, and exit code in the `styrminctl` CLI. | Generated from the Cyclopts command tree at build time. |
| [Python SDK errors](./python-sdk-errors.md) | Which exception the Python SDK raises for each error code, and how a program reads the details of a refused request. | Written by hand from `python_sdk/src/styrmin_sdk/exceptions.py` and `python_sdk/src/styrmin_sdk/resources/_base.py`. |
| [Driver API](./driver-api.md) | Reference for the `driver.styrmin.yml` specification — every field, every action declaration. | Generated from the Pydantic models in `backend/styrmin_backend/driver/`. |
| [Configuration](./configuration.md) | Server and agent configuration: environment variables, Helm values, defaults. | Generated from the Pydantic-settings models and the Helm chart's `values.schema.json`. |

### How the auto-generation will work

Each reference page is paired with a build step that regenerates its
content from the source-of-truth artefact in the repo (GraphQL schema,
Cyclopts command tree, Pydantic models, JSON schema). Until that
pipeline is wired up, the stubs below describe scope and link to the
upstream code as the temporary authoritative source.
