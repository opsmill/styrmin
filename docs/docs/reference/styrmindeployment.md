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

### Rollout fields in `status`

These fields are documented here until the generated reference exists.
They describe the rollout the operator is working on:

- `status.instanceId` — the ID of the application instance whose spec the
  operator last handled. The create, update and resume handlers write it,
  also when the handler fails. The status reporter sends it to the server,
  and sends `spec.instanceId` for a CR that has no `status.instanceId`.
- `status.rolloutStartedAt` — when the create or update handler started
  the current rollout. The readiness timeout counts from it, or from
  `metadata.creationTimestamp` when it is missing. The resume handler
  sets it only when it is missing.
- The `HelmReleaseReady` condition — set to `Unknown` with the reason
  `Progressing` at the start of each rollout. While FluxCD has not
  reported the HelmRelease's current generation ready, it copies the
  status and transition time of FluxCD's `Ready` condition, with the
  reason and message of the failed install or upgrade when there is one.
  It becomes `True` with the reason `FluxReady` when FluxCD reports the
  current generation ready.
- The `HelmReleaseRemediated` condition — a copy of FluxCD's
  `Remediated=True` condition for the current generation: FluxCD rolled
  back or uninstalled a failed release. The operator removes it at the
  start of each rollout.

The condition types are `NetworkPoliciesReady`, `SecretsReady`,
`HelmReleaseReady`, `HelmReleaseRemediated`, `ServicesReady`,
`MiddlewaresReady`, `Ready` and `Deleted`. For how the operator uses
them, see
[When a rollout is ready or failed](../concepts-and-architecture/operator-and-crds.md#when-a-rollout-is-ready-or-failed).

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
