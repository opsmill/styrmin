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
2. **A front door per environment.** Every Styrmin environment gets its
   own ingress controller, which handles traffic to the applications
   deployed in that environment.

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
