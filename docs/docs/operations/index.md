---
title: Operations
sidebar_position: 1
description: How to run the day-2 operations Styrmin was built for — deploy applications, back them up, upgrade them, and clone environments.
---

## Operations

Day-2 operations are what Styrmin exists for. The landing page
advertises **reliable upgrades**, **per-application backups**, and
**environment cloning** as the headline capabilities. This section
walks through each one end-to-end.

> **Status: in progress.** Most pages here are stubs while the
> operational flows stabilise behind the GraphQL API. The functionality
> exists today (with one exception, called out below) and is exercised
> by the E2E test suite; the user-facing walkthroughs will be filled in
> as each flow's UI / CLI surface settles. If you need to run one of
> these operations today, the most up-to-date reference is the E2E
> test for that flow in
> [`backend/tests/e2e/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e).

### What's in here

| Page | What it covers |
|------|----------------|
| [Deploy an application](./deploy-application.md) | Create a new Deployment by picking an Application Driver Version and filling in its parameters. |
| [Backup an existing Deployment](./backup-deployment.md) | Trigger a backup of one Deployment via its driver's backup procedure. |
| [Upgrade an application / deployment](./upgrade-deployment.md) | Move a Deployment to a newer Application Driver Version through the driver-defined upgrade sequence. |
| [Clone an environment](./clone-environment.md) | **Not yet available** — planned for the beta release. Duplicate an environment with live data so changes can be validated before they hit production. |

### Prerequisites for every operation

Every operation in this section assumes:

- Styrmin is installed and reachable. See
  [Installation](../installation/index.mdx).
- You have an Environment ready (and, except for "Deploy an
  application", at least one Deployment in it). See
  [Quickstart](../installation/quickstart.md) for the fastest path.
- For backup: a Backup Storage Location is configured on the
  Environment.

If any of those are missing, start with [Quickstart](../installation/quickstart.md).
