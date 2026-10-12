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

### Why one ingress controller per environment?

An **ingress controller** is the program that accepts incoming HTTP
traffic and routes it to the right service inside the cluster. Styrmin
uses [Traefik](https://traefik.io/) for this.

Styrmin gives every environment its own Traefik instance because:

- **Isolation.** Environments often have different IP whitelists,
  different TLS certificates, or different load balancers in front of
  them. Per-environment Traefik makes that trivial — you configure each
  one independently.
- **Self-contained cloned environments.** When you clone an environment
  (see [why this matters](../introduction/why-styrmin.md)), the
  clone gets its own Traefik too. Applications in the clone reach each
  other through the clone's network, not back to production.
- **Operational blast radius.** A misconfiguration in one environment's
  ingress can't take down another environment.

The per-environment ingress controller is itself just a Styrmin-managed
deployment — Styrmin uses its own driver model to install it. You don't
have to install or manage it. Styrmin installs it when you deploy the
first application into the environment, and removes it after you delete
the last application in the environment. While that removal runs,
Styrmin rejects new deployments into the environment; deploy again once
the removal completes, and Styrmin installs a new ingress controller.

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

Besides the removal after the last application is deleted, Styrmin
removes an environment's ingress controller when `dedicated_ingress` is
turned off and every application of the environment has been redeployed
to the shared ingress class. The next two sections describe when that
happens.

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
   redeployed without the dedicated ingress, and neither the
   applications nor the controller are `PENDING` or `DEPLOYING`. A
   controller that is still being created when you turn the setting off
   is removed once its creation has finished, so no controller is left
   running without a record in Styrmin.

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
  them.
- The update turns `dedicated_ingress` off while the controller is
  `FAILED`: Styrmin redeploys the applications to the shared ingress
  class, then removes the controller.

When an environment's controller reaches `RUNNING` for any reason, for
example after the first deploy creates it, Styrmin also redeploys the
applications of that environment that are not yet at the config they
resolve to.

### Changing the dedicated ingress of an environment

When you update an environment and turn its own `dedicated_ingress`
off, and the cluster does not set `dedicated_ingress`, Styrmin redeploys
the applications to the shared ingress class and removes the
environment's controller once they have moved.

An environment update does not create or redeploy the controller:

- When it turns the environment's own `dedicated_ingress` on, Styrmin
  redeploys the applications at once, and creates the controller the
  next time an application in the environment is deployed, updated or
  upgraded.
- When it changes the values of the environment's own
  `dedicated_ingress`, the controller keeps its previous values. A
  cluster update, including one that submits the stored cluster config
  again, redeploys the controller with the environment's values.

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
  (load balancer IDs, IP whitelists, etc.). These live on the
  Environment record and get passed through to the per-environment
  Traefik.
- **Per deployment:** nothing. The hostname is generated automatically.

### Next

- [**Backups and restores**](./backups-and-restores.md) — the other big
  per-environment subsystem.
- [**The operator and `StyrminDeployment`**](./operator-and-crds.md) —
  what actually creates the ingress objects inside the cluster.
