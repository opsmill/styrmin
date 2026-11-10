---
title: Migrate a driver whose external service renders its own Ingress
sidebar_position: 8
description: Breaking change for drivers that declare a service scope external and render an Ingress for it, with the steps for driver authors and for operators of deployments.
---

## Migrate a driver whose external service renders its own Ingress

Styrmin now builds the Ingress of every service that a driver declares
`scope: external`. Before this change, no code read `scope` to build an
Ingress: the chart rendered every Ingress, and Styrmin patched the class and
the annotations of each one afterwards. A driver that declares a service
`scope: external` and also renders an Ingress for it in its chart now gives
that service two Ingresses on the same host. This is a breaking change to the
driver format, and the beta policy requires this guide
([Beta status](../beta-status.md)).

### Breaking change for drivers that declare an external service

Styrmin builds one Ingress for each service with `scope: external` and `kind`
`http` or `https`. The Ingress is named `styrmin-svc-<driver service name>`
and has the readable host of the service, and the application address when the
service is the first one the driver declares. See
[The Ingress that Styrmin builds for an external service](../concepts-and-architecture/ingress-and-networking.md#the-ingress-that-styrmin-builds-for-an-external-service).

A chart that renders its own Ingress for the same service adds a second
Ingress with the same host or hosts. What an ingress controller does with two
Ingresses on one host depends on the controller. It was not tested.

### When the effect starts

The effect does not wait for a driver version change. It starts when a
deployment runs a Styrmin release that includes this feature: the operator
builds the Ingress of each external service in its next periodic pass, whatever
driver version the deployment is on. Styrmin cannot see whether a chart renders
an Ingress without rendering the chart, so the release has no guard that stops
it. This is a known and accepted effect.

Which deployments are affected:

| Driver and version | Declares an external service | Renders its own Ingress for it | Effect when Styrmin is upgraded |
|---|---|---|---|
| `generic-app` version 1 | yes, `app` | yes | two Ingresses on the same hosts: `styrmin-app` from the chart and `styrmin-svc-app` from Styrmin. The end-to-end test showed this on the earlier driver version. |
| `generic-app` version 2 | yes, `app` | no | one Ingress, `styrmin-svc-app` |
| `infrahub` up to version 5, `infrahub-enterprise` up to version 4 | no: `task-manager` is internal | not applicable | none |
| `infrahub` version 6, `infrahub-enterprise` version 5 | yes, `task-manager` | no: the chart's Prefect Ingress is off | one Ingress for `task-manager`, `styrmin-svc-task-manager` |
| `semaphore`, `simple-app`, `db-test`, `infrahub-mcp` | no | not applicable | none |
| `slurpit` | declares no services | not applicable | none |

The table lists the drivers in this repository, read from their
`driver.styrmin.yml` and `values.j2.yml`. Only `generic-app`, `infrahub` and
`infrahub-enterprise` declare an external service. How many drivers outside
this repository declare `scope: external` and render their own Ingress is not
known. It sets the size of this breaking change.

### Steps for a driver author

1. List the services under `spec.services` that declare `scope: external`.
2. For each one, check whether the chart renders an Ingress for it, including an
   Ingress of a subchart. Run `helm template` with your values and look for
   `kind: Ingress`.
3. Turn that Ingress off in `values.j2.yml`. The key depends on the chart. For
   example, the `infrahub` drivers set `prefect-server.ingress.enabled: false`,
   and `generic-app` no longer has an `ingress:` block.
4. Check which Ingress carries the application address,
   `<driver name>-<deployment id>.<fqdn suffix>`. Styrmin puts it on the Ingress
   of the first service in `spec.services`, and only when that service is
   `external`. If a chart Ingress that you keep for an internal service already
   uses `{{ services['<name>'].primary_fqdn }}` as its host, keep that service
   first and internal, as the `infrahub` drivers do. Otherwise two Ingresses claim
   the host.
5. If you want the chart to keep an Ingress for a service, declare the service
   `scope: internal`. Styrmin then builds no Ingress for it, and a
   [service ingress override](../concepts-and-architecture/service-ingress-overrides.md)
   cannot apply to it.
6. Increase `spec.version` and load the driver. See
   [Load a driver](./loading-drivers.md).
7. Upgrade each deployment to the new driver version.
8. In a test environment, read the Ingresses of a deployment:

   ```shell
   kubectl get ingress -n styrmin-<deployment-id>
   ```

   The deployment has one Ingress for each external service, named
   `styrmin-svc-<service name>`, and no Ingress from the chart for that service.

### Steps for an operator of deployments

1. Before you upgrade Styrmin, find the deployments whose driver version
   declares an external service and renders its own Ingress. For the drivers in
   this repository, these are the deployments of `generic-app` version 1.
2. After the upgrade, or on a cluster that already runs this release, list the
   Ingresses of the cluster and look for two Ingresses with the same host:

   ```shell
   kubectl get ingress -A
   ```

3. Load the driver version that renders no Ingress, and upgrade the deployment
   to it. For `generic-app`, this is version 2: see
   [Upgrading from driver version 1](./generic-app.md#upgrading-from-driver-version-1).
4. Read the Ingresses again. The deployment has one Ingress for each external
   service.

An upgrade of a running `generic-app` deployment from version 1 to version 2 was
not tested. The end-to-end test deploys version 2 on a new deployment and finds
one Ingress, and deployed version 1 on the same Styrmin code and found two.

### What you see when you move Infrahub to the new driver version

`infrahub` version 6 and `infrahub-enterprise` version 5 declare `task-manager`
`scope: external` and turn the chart's Prefect Ingress off. When you upgrade a
deployment to them:

- The Prefect UI Ingress moves from the Helm chart to an Ingress that Styrmin
  builds, named `styrmin-svc-task-manager`.
- The host of the Prefect UI does not change, unless you set a
  [service ingress override](../concepts-and-architecture/service-ingress-overrides.md)
  for `task-manager`. It is `task-manager-<environment name>.<fqdn suffix>`.
- The Ingress for the `infrahub` service stays as the chart renders it, with
  its hosts, including the application address.
- The Prefect UI calls the address that `prefectUiApiUrl` in `values.j2.yml`
  builds from the host of `task-manager`. It follows an override.

What was not verified: an upgrade of a running Infrahub deployment. The
end-to-end tests deploy the new driver version on a new deployment. So it is not
known whether the Prefect UI stops answering while Helm removes the chart's
Ingress and the operator builds the new one, or for how long. The order of the
Helm upgrade and the operator's pass decides it, and the operator's pass runs
every 60 seconds by default. That delay was not measured.

### Moving back to a driver version that renders its own Ingress

A change to an earlier driver version has these effects:

- A deployment that moves to a driver version that declares an external service
  and renders its own Ingress for it, such as `generic-app` version 1, gets two
  Ingresses on the same host, as in
  [When the effect starts](#when-the-effect-starts).
- A deployment that moves from `infrahub` version 6 to version 5, where
  `task-manager` is internal, no longer has a Styrmin-built Ingress for it. The
  operator deletes `styrmin-svc-task-manager` when the Ingress is no longer
  required, and the chart of version 5 renders the Prefect Ingress. The
  operator's deletion of a stale Ingress is covered by unit tests, and the move
  back was not run on a cluster.
- A stored service ingress override on `task-manager` refuses the change, with
  `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`, because version 5 declares the
  service internal. Clear the override first. See
  [Change a deployment's driver version](./changing-driver-versions.md#stored-service-ingress-overrides).

What happens to the `styrmin-svc-*` Ingresses when you roll Styrmin back to a
release without this feature is not known. It was not tested.

### What is not known

- How many drivers outside this repository declare `scope: external` and
  render their own Ingress.
- Whether the Prefect UI of a running Infrahub deployment is interrupted when
  the deployment moves to the new driver version, and for how long.
- What an ingress controller does with two Ingresses on the same host.
- How a backup and a restore of an environment behave when its deployments
  have Styrmin-built Ingresses.
- How long the operator takes to build an Ingress at its default interval of 60
  seconds. It was measured at about one second in a test setup whose interval is
  5 seconds.

### Next steps

- [Create a driver](./creating-a-driver.md#step-6-declare-services): declare
  services.
- [Service ingress overrides](../concepts-and-architecture/service-ingress-overrides.md):
  publish one service with another class or suffix.
- [Change a deployment's driver version](./changing-driver-versions.md): the
  checks on a driver version change.
