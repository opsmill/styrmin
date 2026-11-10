---
title: StyrminDeployment CRD
sidebar_position: 2
description: Field-by-field reference for the StyrminDeployment Kubernetes Custom Resource Definition.
---

## `StyrminDeployment` CRD

:::info Stub page — to be generated

This page will be generated from the OpenAPI schema embedded in the
operator. The text below describes the scope of the page, not its final
content.

Until the generation step exists, these files define the CRD:
[`backend/styrmin_backend/operator/crds/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/operator/crds)
and the kopf handlers under
[`backend/styrmin_backend/operator/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/operator).

:::

### Scope

`StyrminDeployment` is the custom resource that the operator
reconciles. Its `spec` contains the embedded `GlobalContext`, which
describes what must run in the cluster for one deployment.

The page will document each field:

- `metadata`: name, namespace, labels, annotations
- `spec`: the embedded `GlobalContext` and each sub-context
  (`cluster`, `environment`, `deployment`, `instance`, `application`,
  `components`, `utilities`)
- `status`: `phase`, `conditions`, `observedGeneration`, and the
  readiness of each component

### Annotations

Annotations are not part of the OpenAPI schema, so this section stays
when the page is generated.

- `styrmin.io/instance-sequence`: the number of the instance in
  `spec.instanceId` among the instances of the deployment: 1 for the
  first instance, then one more for each new instance. Styrmin manages
  it; do not edit it. A workflow does not replace a `StyrminDeployment`
  that holds a higher number than its own instance. See
  [Several changes in quick succession](../concepts-and-architecture/reconciliation.md#several-changes-in-quick-succession)
  for what you see and how to recover after an edit.

### Ingress objects that the operator builds

For each service in `spec` that has `scope: external` and `kind` `http` or
`https`, the operator creates an Ingress named `styrmin-svc-<driver service name>`
in the deployment's namespace. It is not part of the `HelmRelease`. The operator
builds it from the resolved context in its periodic pass, as it does for the
network policies, services and secrets that it builds, and deletes it when the
context no longer requires it. It has the labels `app.kubernetes.io/managed-by`,
`styrmin.io/utility-kind: ingress`, `styrmin.io/release-reference` and
`styrmin.io/service-name`. No condition in `status` reports on these Ingresses:
the condition types listed below have none for them.

The default interval of the periodic pass is 60 seconds. See
[The Ingress that Styrmin builds for an external service](../concepts-and-architecture/ingress-and-networking.md#the-ingress-that-styrmin-builds-for-an-external-service)
and [Service ingress overrides](../concepts-and-architecture/service-ingress-overrides.md).

### Rollout fields in `status`

These fields are documented here until the generated reference exists.
They describe the rollout that the operator is running:

- `status.instanceId`: the ID of the instance whose spec the operator
  last handled. The create, update and resume handlers write it, even
  when the handler fails. The status reporter sends it to the server,
  and sends `spec.instanceId` for a `StyrminDeployment` that has no
  `status.instanceId`.
- `status.rolloutStartedAt`: the time when the create or update handler
  started the current rollout. The readiness timeout counts from it, or
  from `metadata.creationTimestamp` when it is missing. The resume
  handler sets it only when it is missing.
- The `HelmReleaseReady` condition: set to `Unknown` with the reason
  `Progressing` at the start of each rollout. While FluxCD has not
  reported the current generation of the `HelmRelease` as ready, the
  condition copies the status and transition time of FluxCD's `Ready`
  condition, with the reason and message of the failed install or
  upgrade when there is one. It becomes `True` with the reason
  `FluxReady` when FluxCD reports the current generation as ready.
- The `HelmReleaseRemediated` condition: a copy of FluxCD's
  `Remediated=True` condition for the current generation, which means
  that FluxCD rolled back or uninstalled a failed release. The operator
  removes it at the start of each rollout.

The condition types are `NetworkPoliciesReady`, `SecretsReady`,
`HelmReleaseReady`, `HelmReleaseRemediated`, `ServicesReady`,
`MiddlewaresReady`, `Ready` and `Deleted`. For how the operator uses
them, see
[When a rollout is ready or failed](../concepts-and-architecture/operator-and-crds.md#when-a-rollout-is-ready-or-failed).

### Generation source

- **Schema**: the OpenAPI schema of the CRD, which the kopf operator
  also validates against
- **Build step**: not defined yet; it will write Markdown from the
  schema into this file

### Related pages

- [Concepts and architecture → The operator and `StyrminDeployment`](../concepts-and-architecture/operator-and-crds.md):
  what the operator does with each `StyrminDeployment`.
- [Concepts and architecture → Reconciliation](../concepts-and-architecture/reconciliation.md):
  how Styrmin turns the `spec` of a `StyrminDeployment` into Kubernetes
  resources.
