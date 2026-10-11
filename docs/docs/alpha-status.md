---
title: Alpha status
description: What "alpha" means for Styrmin today — known limitations, broken features, and how to give feedback.
---

## Alpha status

Styrmin is currently in **alpha**. We're using it day-to-day and we want
you to try it too, but you should know what that means before you commit
to running it in anger:

- APIs, CLI flags, GraphQL schema, and driver formats may still change
  between releases.
- Breaking changes are possible without a deprecation window during the
  alpha phase. We try to call them out in the
  [Changelog](./changelog.md), but please read release notes before
  upgrading.
- Styrmin is **not yet recommended for production-critical workloads**.
  It is suitable for lab, staging, and internal-tooling deployments
  where you can tolerate the occasional rough edge.
- Expect rough edges in the UI, error messages, and documentation. We
  want to hear about them — see
  [Giving feedback](#giving-feedback) below.

### Coming before beta

These features are deliberately not in the alpha and are tracked for the
beta release:

- **Cloning an environment** — copy an environment (including selected
  applications) into a new, network-isolated environment. Tracked in
  [opsmill/styrmin#6](https://github.com/opsmill/styrmin/issues/6).

### Known limitations

- **Infrahub does not answer queries while its database is backed up.**
  The Infrahub driver backs up Neo4j Community by pausing Neo4j while
  Velero copies its data volume, so Infrahub API requests wait or time out
  until the backup finishes. See
  [Backups and restores](./concepts-and-architecture/backups-and-restores.md).

If you hit something that looks broken and it's not listed above, please
file an issue — see below.

### Giving feedback

We're actively shaping Styrmin and feedback from early users carries a
lot of weight right now.

- **Bugs and feature requests** → open a ticket on
  [GitHub Issues](https://github.com/opsmill/styrmin/issues/new/choose).
  If you're working inside the repository with an AI coding assistant,
  the `create-issue` skill (`/create-issue`) will format the issue to
  the project's conventions and apply the right labels — please use it
  for any bug report or feature request originating from your local
  workflow.
- **General discussion, questions, or "is this the right approach?"**
  → join the [OpsMill Discord](https://discord.gg/opsmill). It's the
  fastest way to reach the team and the rest of the community.
