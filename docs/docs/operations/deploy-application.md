---
title: Deploy an application
sidebar_position: 2
description: Create a new Deployment in an Environment by picking an Application Driver Version and filling in its parameters.
---

## Deploy an application

:::info Stub page

This guide is a placeholder while the deploy flow stabilises behind
the GraphQL API. The capability exists today and is exercised by the
deploy E2E scenarios in `backend/tests/e2e/`. This page will be filled
in once the user-facing CLI / SDK / UI surface is final.

For now, see the E2E flows in
[`backend/tests/e2e/scenarios/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e)
for the authoritative sequence of API calls.

:::

### What you'll be able to do here

Create a new Deployment in an Environment by picking one Application
Driver Version, choosing an Application Version it supports, and
filling in the driver's user-facing parameters. Styrmin generates an
Instance, writes a `StyrminDeployment` CRD, and the agent reconciles
the cluster to match.

### Outline (to be filled in)

1. **Pick the Environment** the application will live in.
2. **Pick an Application Driver Version.** Either one of the bundled
   drivers (Infrahub, Semaphore, …) or one you loaded yourself —
   see [Loading a driver](../drivers/loading-drivers.md).
3. **Pick an Application Version** supported by the chosen Driver
   Version (the driver declares the supported semver range).
4. **Fill in parameters.** The driver declares typed parameters; the
   UI / CLI / SDK surface them as a form / flags / kwargs.
5. **Create the Deployment.** Single CLI / SDK / GraphQL call.
6. **Watch the rollout.** The Deployment transitions through
   `PENDING` → `DEPLOYING` → `RUNNING`. The setup hook runs through
   `pre` → `core` → `post`; the status reporter posts pod and
   deployment state back to the server.

### Related

- [Concepts and Architecture → What is an Application Driver?](../concepts-and-architecture/what-is-a-driver.md)
  — the unit you're picking from.
- [Drivers → Loading a driver](../drivers/loading-drivers.md) — if the
  driver you want isn't registered yet.
- [Concepts and Architecture → Reconciliation](../concepts-and-architecture/reconciliation.md)
  — what happens between "create Deployment" and "cluster matches".
