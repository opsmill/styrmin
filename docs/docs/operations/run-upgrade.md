---
title: Run an upgrade
sidebar_position: 5
description: Upgrade a deployment to a newer Application Driver Version through the driver-defined upgrade sequence — stop components, run migrations, restart, verify.
---

## Run an upgrade

:::info Stub page

This guide is a placeholder while the upgrade flow stabilises behind
the GraphQL API. The capability exists today and is exercised by the
upgrade E2E scenarios in `backend/tests/e2e/`. This page will be
filled in once the user-facing CLI / SDK surface is final.

For now, see the E2E flows in
[`backend/tests/e2e/scenarios/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e)
for the authoritative sequence of API calls.

:::

### What you'll be able to do here

Upgrade a Deployment to a newer Application Driver Version. Complex
upgrade processes (stop workers, run database migrations, restart,
smoke-test) are encoded **once** in the driver's upgrade hook and run
the same way every time — not improvised in production at 2am.

### Outline (to be filled in)

1. **Load the newer Application Driver Version** if it isn't already
   registered. See [Loading a driver](../drivers/loading-drivers.md).
2. **Choose a target Application Version** supported by the new
   Application Driver Version.
3. **Rehearse on a clone** (recommended). Clone the Environment, run
   the upgrade in the clone first, verify, then run it for real.
4. **Trigger the upgrade.** Single CLI / SDK / GraphQL call against
   the Deployment, referencing the target Application Driver Version
   and Application Version.
5. **Watch the upgrade hook run.** The driver's `upgrade` hook runs
   through `pre` → `core` → `post` modes. Status flows back to the
   server via the status reporter.
6. **Verify.** Deployment is `RUNNING`, on the new versions, and any
   driver-defined verification actions have passed.

### Related

- [Clone an environment](./clone-environment.md) — rehearse upgrades
  against real production data without risk.
- [Concepts and Architecture → Lifecycle hooks and actions](../concepts-and-architecture/hooks-and-actions.md)
  — what the `upgrade` hook actually runs, and in what order.
- [Drivers → Creating a driver](../drivers/creating-a-driver.md) —
  if you need to encode a new upgrade sequence yourself.
