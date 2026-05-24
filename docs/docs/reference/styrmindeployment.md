---
title: StyrminDeployment CRD
sidebar_position: 2
description: Field-by-field reference for the StyrminDeployment Kubernetes Custom Resource Definition.
---

## `StyrminDeployment` CRD

:::info Stub page — to be auto-generated

This page will be generated from the OpenAPI schema embedded in the
operator. The information below is a placeholder describing scope, not
the final content.

Until the auto-generation pipeline is wired up, the authoritative
source is
[`backend/styrmin_backend/operator/crds/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/operator/crds)
and the kopf handlers under
[`backend/styrmin_backend/operator/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/operator).

:::

### Scope

`StyrminDeployment` is Styrmin's primary Custom Resource Definition.
It carries the embedded `GlobalContext` in `spec` and is the
operator's single source of truth about what should be running in the
cluster.

This page will document, field by field:

- `metadata` — name, namespace, labels, annotations
- `spec` — the embedded `GlobalContext` and every sub-context
  (`cluster`, `environment`, `deployment`, `instance`, `application`,
  `components`, `utilities`)
- `status` — `phase`, `conditions`, `observedGeneration`,
  per-component readiness

### Auto-generation source

- **Schema**: the CRD's OpenAPI schema (the same one the kopf operator
  validates against)
- **Build step**: TBD — emit Markdown from the schema and write it
  into this file

### Related

- [Concepts and Architecture → The operator and `StyrminDeployment`](../concepts-and-architecture/operator-and-crds.md)
  — what the CRD does at runtime.
- [Concepts and Architecture → Reconciliation](../concepts-and-architecture/reconciliation.md)
  — how the CRD's `spec` gets reconciled into Kubernetes resources.
