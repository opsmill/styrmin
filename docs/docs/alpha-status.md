---
title: Alpha status
description: What "alpha" means for Styrmin today, the known broken features, and how to give feedback.
---

## Alpha status

Styrmin is in **alpha**. Before you run it for real workloads, note the
following:

- APIs, CLI flags, the GraphQL schema, and the driver format can change
  between releases.
- A release can include breaking changes without a deprecation period.
  The [Changelog](./changelog.md) lists them, but read the release notes
  before you upgrade.
- Styrmin is **not recommended for production-critical workloads yet**.
  Use it for lab, staging, and internal-tooling deployments where you
  can accept occasional defects.
- The UI, the error messages, and the documentation have incomplete
  parts. Report them: see [Giving feedback](#giving-feedback).

### Known broken features

- **The backup of the `infrahub` driver fails.** The Neo4j pre-backup
  hook runs a command that only Neo4j Enterprise has, against the Neo4j
  Community image of the `infrahub` driver, so the backup ends in the
  `PartiallyFailed` state. Tracked in
  [opsmill/styrmin#263](https://github.com/opsmill/styrmin/issues/263).

If something does not work and it is not listed above, open an issue:
see below.

### Giving feedback

Styrmin is still changing, so feedback from early users has the most
effect now.

- **Bugs and feature requests**: open an issue on
  [GitHub Issues](https://github.com/opsmill/styrmin/issues/new/choose).
  If you work in the repository with an AI coding assistant, run the
  `create-issue` skill (`/create-issue`) for each bug report or feature
  request. It formats the issue to the project's conventions and applies
  the project's labels.
- **Questions and general discussion**: join the
  [OpsMill Discord](https://discord.gg/opsmill). It is the fastest way
  to reach the Styrmin team and other users.
