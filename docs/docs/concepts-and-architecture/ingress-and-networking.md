---
title: Ingress and networking
sidebar_position: 5
description: How a deployment becomes reachable on a URL, and how environments are kept apart on the network.
---

## Ingress and networking

When you deploy an application through Styrmin, it ends up on a URL that
you can hit from a browser or another service. This page explains how
that happens.

### Two layers of ingress

There are two different "front doors" in a Styrmin cluster:

1. **The front door for Styrmin itself.** The UI and GraphQL API at
   something like `styrmin.example.com`. You install this once when you
   set up the cluster (see the
   [DigitalOcean guide](../installation/digitalocean.md) for a worked
   example) and it never changes per deployment.
2. **A front door per environment.** A Styrmin environment can get its
   own ingress controller, which handles traffic to the applications
   deployed in that environment (see
   [Dedicated ingress controller or shared ingress class](#dedicated-ingress-controller-or-shared-ingress-class)).

The reason for the split: the Styrmin server is a single thing with a
fixed URL. The applications are many, change often, and need to be
isolated from each other.

### Why an environment can have its own ingress controller

An **ingress controller** is the program that accepts incoming HTTP
traffic and routes it to the right service inside the cluster. Styrmin
uses [Traefik](https://traefik.io/) as the dedicated ingress controller
of an environment.

An environment gets its own Traefik instance only when
`dedicated_ingress` is set for it (see
[Dedicated ingress controller or shared ingress class](#dedicated-ingress-controller-or-shared-ingress-class)).
A dedicated ingress controller gives the environment:

- **Isolation.** Environments often have different IP allow lists,
  different TLS certificates, or different load balancers in front of
  them. With a dedicated Traefik instance, you configure each
  environment's ingress on its own.
- **Self-contained cloned environments.** When you clone an environment
  (see [why this matters](../introduction/why-styrmin.md)) and
  `dedicated_ingress` is set for the new environment, the new
  environment gets its own Traefik instance too. Applications in the
  clone reach each other through the clone's network, not back to
  production.
- **Separate failures.** A misconfiguration in one environment's ingress
  does not stop the ingress of another environment.

The dedicated ingress controller is itself a deployment that Styrmin
manages: Styrmin installs it with its own driver model, and you do not
install or manage it. In an environment that has `dedicated_ingress`
set and no controller yet, Styrmin installs it when you deploy, update
or upgrade an application in the environment, or when you update the
cluster config and the environment has applications. Styrmin removes it
when no application uses it any more:

- after you delete the last application in the environment
- after `dedicated_ingress` is turned off for the environment and every
  application has been redeployed to the cluster's shared ingress class
  (see the next sections)

While the removal runs and `dedicated_ingress` is still set for the
environment, Styrmin rejects deploying, updating and upgrading
applications in the environment. Try again once the removal completes,
and Styrmin installs a new ingress controller.

### Dedicated ingress controller or shared ingress class

The `dedicated_ingress` setting decides whether an environment gets its
own ingress controller:

- When the environment sets `dedicated_ingress`, or the environment does
  not set it and the cluster does, the environment gets a dedicated
  ingress controller and its applications are served through it. Any
  `dedicated_ingress` object turns it on, including an empty one (`{}`).
- When neither the environment nor the cluster sets `dedicated_ingress`,
  the applications' Ingress resources use the cluster's `ingress_class`
  (`traefik` by default), and the shared ingress controller of the
  Kubernetes cluster for that class serves them.

An environment that does not set `dedicated_ingress` takes the
cluster's value, so an environment cannot turn off a dedicated ingress
that the cluster sets.

The next two sections describe how Styrmin changes the ingress of an
environment when `dedicated_ingress` changes on the cluster or on the
environment.

### Changing the dedicated ingress on the cluster

When you update the cluster config (with `styrminctl clusters update`,
the SDK, the `updateCluster` GraphQL mutation or the cluster detail
page) and the update turns `dedicated_ingress` on, changes its values,
or turns it off, Styrmin changes the ingress of each environment that
takes the cluster's value. It orders the changes so that the
applications stay reachable. Environments that set their own
`dedicated_ingress` keep their own value. See
[`clusters update`](../reference/styrminctl.md#clusters-update--change-a-clusters-config)
for the rest of the update.

When the update turns `dedicated_ingress` on or changes its values:

1. Styrmin creates the environment's ingress controller, or redeploys it
   with the new values. In an environment without applications, Styrmin
   creates no controller; it creates one when you deploy the first
   application, as before.
2. The applications stay on their current ingress while the controller
   is not `RUNNING` with the new values.
3. When the controller reaches `RUNNING`, Styrmin redeploys the
   applications onto it.

When the update turns `dedicated_ingress` off:

1. Styrmin redeploys the applications to the cluster's `ingress_class`
   at once.
2. Styrmin removes the controller once every application has been
   redeployed without the dedicated ingress, no application is
   `PENDING`, `DEPLOYING`, `FAILED` or `RESTORING`, and the controller is
   not `PENDING` or `DEPLOYING`. A controller that is still being
   created when you turn the setting off is removed once its creation
   has finished, so no controller is left running without a record in
   Styrmin.

A `FAILED` application keeps the controller because FluxCD rolls a
failed upgrade back to the previous release, whose Ingress can still use
the controller. Styrmin removes the controller once the application is
`RUNNING` again or deleted.

When the controller has failed or is being removed:

- The controller is `FAILED` and the update does not change the
  environment's `dedicated_ingress`: Styrmin redeploys the applications
  for the other changed values and leaves the controller as it is.
- A new or redeployed controller ends `FAILED`: the applications that
  wait to move onto it stay on their current config, because Styrmin
  never moves an application onto a controller that is not `RUNNING`.
  Submit the config again: Styrmin redeploys the controller again, and
  moves the applications once it is `RUNNING`.
- The controller is being removed (`DELETING`): Styrmin does not create
  a second controller, and the applications that would move onto one
  stay on their current config. Submit the config again once the
  removal has finished; Styrmin then creates a new controller and moves
  them. If the controller stays `DELETING`, see
  [A controller that stays `DELETING`](#a-controller-that-stays-deleting).
- The update turns `dedicated_ingress` off while the controller is
  `FAILED`: Styrmin redeploys the applications to the shared ingress
  class, then removes the controller.

When an environment's controller reaches `RUNNING` for any reason, for
example after the first deploy creates it, Styrmin also redeploys the
applications of that environment that are not yet at the config they
resolve to.

### A controller that stays `DELETING`

A known race in the operator can stop the removal of a dedicated
ingress controller ([#446](https://github.com/opsmill/styrmin/issues/446)). Changes to `dedicated_ingress` remove controllers
more often, so you are more likely to see it after a cluster update.

You see these symptoms:

- The controller deployment stays `DELETING` in Styrmin for more than a
  few minutes.
- Its namespace, `styrmin-<controller-id>`, stays `Terminating`.
- Its `StyrminDeployment` custom resource, also named
  `styrmin-<controller-id>`, still has the `styrmin.io/kopf-finalizer`
  finalizer although the operator logged `Deletion is processed`.

The operator's delete handler and its timer ran at the same moment, and
the operator kept the finalizer. To recover, add any annotation to the
custom resource. The operator then runs the delete handler again and
removes the finalizer:

```bash
kubectl annotate styrmindeployments.styrmin.io styrmin-<controller-id> \
  -n styrmin-<controller-id> styrmin.io/retry-delete="$(date +%s)" --overwrite
```

The namespace is then deleted, Styrmin marks the controller as deleted,
and you can submit the cluster config again to move the applications
that waited.

### Changing the dedicated ingress of an environment

When you update an environment (with the `updateEnvironment` GraphQL
mutation or the SDK) and the update turns the environment's own
`dedicated_ingress` on, changes its values, or turns it off, Styrmin
changes the environment's controller in the same order as a cluster
update. See
[Changing the dedicated ingress on the cluster](#changing-the-dedicated-ingress-on-the-cluster).

- When the update turns `dedicated_ingress` on or changes its values,
  Styrmin creates the controller or redeploys it with the new values.
  The applications stay on their current ingress until the controller
  is `RUNNING` with the new values, then Styrmin redeploys them onto it.
  In an environment without applications, Styrmin creates no controller
  until you deploy the first application.
- When the update turns `dedicated_ingress` off and the cluster sets
  `dedicated_ingress`, the environment takes the cluster's value.
  Styrmin redeploys the controller with the cluster's values when they
  differ, in the same order.
- When the update turns `dedicated_ingress` off and the cluster does not
  set it, Styrmin redeploys the applications to the shared ingress class
  at once, and removes the controller once they have moved.

A failed controller, and a controller that is being removed, are handled
as in a cluster update. When you submit the environment config again,
Styrmin retries a controller that could not be started, and redeploys a
controller whose values differ from the environment's value, for example
after an environment update made with an earlier Styrmin release, which
changed only the applications.

The **Configuration** tab of the environment page does not edit
`dedicated_ingress`. While the environment sets it, including an empty
`dedicated_ingress: {}` that turns the controller on with default
values, the tab blocks saving, because a save from the tab would turn
`dedicated_ingress` off.

### Known limitation: a deployment that sets its own `dedicated_ingress` waits for the controller

A deployment can set its own `dedicated_ingress` in its config. When an
environment update changes the resolved config of such a deployment,
and the deployment's value differs from the environment's, Styrmin
redeploys the deployment only once the environment's controller is
`RUNNING` with the environment's values. This happens even when the
update does not change `dedicated_ingress`:

- The update changes only environment variables while the controller
  is `DEPLOYING`: the deployment keeps its current config, and Styrmin
  redeploys it when the controller reaches `RUNNING`.
- The update changes only environment variables while the controller
  is `FAILED`: Styrmin also redeploys the controller, and the
  deployment waits for it.

When the controller is `RUNNING` with the environment's values, Styrmin
redeploys the deployment at once. A cluster update holds such a
deployment back in the same way. [#453](https://github.com/opsmill/styrmin/issues/453)
tracks this.

### How an application URL gets assigned

Each application driver declares the **services** it exposes — name,
port, scope (internal vs external). When Styrmin deploys an application,
it generates a hostname for every external service based on a
**fully-qualified domain name (FQDN) suffix** you configured at the
cluster level.

The convention is roughly:

```text
<service-name>-<deployment-id>.<fqdn-suffix>
```

So a deployment of `infrahub` with a `web` service on a cluster with
suffix `styrmin.io` ends up reachable at something like:

```text
http://infrahub-<deployment-id>.styrmin.io
```

You don't have to invent or register that hostname per deployment — it
falls out of the configuration. The only DNS setup you need is a
**wildcard record** (`*.styrmin.io`) pointing at the environment's
ingress, and every deployment gets a working URL automatically.

### Networking between applications

When two applications in the same environment need to talk to each
other — say, Infrahub talking to a Postgres deployed alongside it — they
use Kubernetes service names, not external hostnames. That keeps the
traffic inside the cluster and means cloned environments are naturally
self-contained: the Infrahub in the clone talks to the Postgres in the
clone, not back to production.

The driver decides which services are internal and which are external.
Internal services don't get an external hostname; external ones do.

### What you actually have to configure

- **Once per cluster:** an FQDN suffix and an ingress in front of
  the Styrmin server itself. Both are part of the install — see the
  [DigitalOcean guide](../installation/digitalocean.md) for what this
  looks like in practice on a real cloud.
- **Once per environment:** any environment-specific ingress settings
  (load balancer IDs, IP allow lists, etc.). These live on the
  Environment record and get passed through to the environment's
  dedicated Traefik instance.
- **Per deployment:** nothing. The hostname is generated automatically.

### Next

- [**Backups and restores**](./backups-and-restores.md) — the other big
  per-environment subsystem.
- [**The operator and `StyrminDeployment`**](./operator-and-crds.md) —
  what actually creates the ingress objects inside the cluster.
