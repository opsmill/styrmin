---
title: Operations
sidebar_position: 1
description: How to run the day-2 operations Styrmin was built for — clone an environment, back up a stack, restore, and upgrade.
---

## Operations

Day-2 operations are what Styrmin exists for. The landing page
advertises **environment cloning**, **stack-wide backups**, and
**reliable upgrades** as the headline capabilities. This section walks
through each one end-to-end.

> **Status: in progress.** These guides are currently stubs while the
> operational flows stabilise behind the GraphQL API. The functionality
> exists today and is exercised by the E2E test suite; the user-facing
> walkthroughs below will be filled in as each flow's UI / CLI surface
> settles. If you need to run one of these operations today, the most
> up-to-date reference is the E2E test for that flow in
> [`backend/tests/e2e/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e).

### What's in here

| Page | What it covers |
|------|----------------|
| [Clone an environment](./clone-environment.md) | Duplicate an environment — applications, configuration, and live data — to validate upgrades and changes before they hit production. |
| [Back up a stack](./back-up-stack.md) | Trigger a backup across every application in an environment in a single operation. |
| [Restore a stack](./restore-stack.md) | Restore an environment from a previous backup. |
| [Run an upgrade](./run-upgrade.md) | Move a deployment to a newer Application Driver Version through the driver-defined upgrade sequence. |

### Prerequisites for every operation

Every operation in this section assumes:

- Styrmin is installed and reachable. See
  [Installation](../installation/index.mdx).
- You have an Environment with at least one Deployment in it. See
  [Quickstart](../installation/quickstart.md) for the fastest path.
- For backup and restore: a Backup Storage Location is configured on
  the Environment.

If any of those are missing, start with [Quickstart](../installation/quickstart.md).
