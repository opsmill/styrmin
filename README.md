# Styrmin

> Lifecycle management for your infrastructure automation stack.

📖 Documentation: <https://styrmin.pages.dev>

Styrmin is an application platform that manages the **full lifecycle** of
your infrastructure automation stack — Infrahub, Ansible, Grafana,
Prometheus, and the tooling around them — as a single system, not one
application at a time.

These tools don't run in isolation: they need to be deployed together,
backed up together, upgraded together, and tested together. Doing that by
hand means a Helm chart per application, a backup script per application,
a brittle upgrade runbook per application, and no realistic way to
rehearse a change before it hits production. Styrmin gives you one system
for all of it.

Each application brings a **driver** — a versioned specification that
tells Styrmin how to deploy, configure, back up, and upgrade it correctly.
Styrmin handles the rest, including the cluster-specific details that
today require specialist knowledge to get right.

## The capabilities that nothing else provides

- **Clone an entire environment** — including live production data — to
  validate upgrades against real data before touching production.
- **Back up the whole stack** in a single operation. Each driver knows
  how to back up its application correctly (Neo4j ≠ Postgres ≠ disk
  snapshots — the driver handles it).
- **Upgrade reliably** through driver-defined sequences that stop
  components, run migrations, restart, and verify. The complex bits are
  encoded once and run the same way every time.

Styrmin runs on Kubernetes as its underlying infrastructure layer, but
that's an implementation detail — the goal is for teams to get a managed
infrastructure experience without needing to think about Kubernetes at
all. See [Why Styrmin?](https://styrmin.pages.dev/docs/getting-started/why-styrmin)
for the full positioning, and how Styrmin compares to ArgoCD, Flux, and
manual Helm.

## Quickstart

You need [Docker](https://docs.docker.com/get-docker/),
[`kubectl`](https://kubernetes.io/docs/tasks/tools/),
[`helm`](https://helm.sh/docs/intro/install/),
[`vcluster`](https://www.vcluster.com/docs/getting-started/setup), and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) on your
`PATH`. Then:

```bash
uv sync
uv run invoke build
uv run invoke start
```

When it finishes, open <http://styrmin.local.styrmin.io:8080> and log in
with `admin` / `styrmin`.

The full walkthrough — what each step does, the lifecycle commands, and
troubleshooting — lives in the
[Quickstart guide](https://styrmin.pages.dev/docs/getting-started/quickstart).
For a production install, see
[Installation](https://styrmin.pages.dev/docs/installation).

## Documentation

| What you want | Where it lives |
|---------------|----------------|
| Why Styrmin, how it compares to ArgoCD/Flux | [Why Styrmin?](https://styrmin.pages.dev/docs/getting-started/why-styrmin) |
| Conceptual model and core vocabulary | [Platform Overview](https://styrmin.pages.dev/docs/getting-started/overview) |
| Install on your laptop or in a cloud | [Installation](https://styrmin.pages.dev/docs/installation) |
| Write a driver | [Creating a Driver](https://styrmin.pages.dev/docs/drivers/creating-a-driver) |
| Architecture, ingress, backups, hooks | [How It Works](https://styrmin.pages.dev/docs/how-it-works) |
| The canonical project glossary | [`CONTEXT.md`](CONTEXT.md) |
| Decisions behind the architecture | [`dev/adr/`](dev/adr/) |
| Contributor / agent guide | [`AGENTS.md`](AGENTS.md) |

## Development

This section is for contributors to Styrmin itself.

### Setup

```bash
uv sync                          # Python deps (root + workspace + dev group)
cd frontend && pnpm install      # frontend deps (required for codegen)
uv run invoke pre-commit-install # local pre-commit + pre-push hooks
```

### Common tasks

```bash
uv run invoke test               # backend tests
cd frontend && pnpm test         # frontend tests
uv run invoke format lint        # format + lint everything (Python, Markdown, YAML)
uv run invoke generate           # regenerate SDK and frontend types from GraphQL
```

Run a development environment in Docker Compose (instead of the bundled
vcluster demo):

```bash
uv run invoke dev.build dev.start    # build + start
uv run invoke dev.bootstrap          # seed cluster, env, BSL, drivers
uv run invoke dev.stop dev.clean     # stop and wipe
```

### Project layout

- [`backend/`](backend/) — Python backend (FastAPI + GraphQL + agent).
  See [`backend/AGENTS.md`](backend/AGENTS.md).
- [`frontend/`](frontend/) — React + TypeScript SPA.
  See [`frontend/AGENTS.md`](frontend/AGENTS.md).
- [`python_sdk/`](python_sdk/) — async Python client SDK.
  See [`python_sdk/AGENTS.md`](python_sdk/AGENTS.md).
- [`cli/`](cli/) — `styrminctl` command-line client.
- [`driver/`](driver/) — bundled application drivers and the driver
  format reference.
- [`docs/`](docs/) — public Docusaurus site published to
  <https://styrmin.pages.dev>.
- [`dev/`](dev/) — internal developer documentation
  ([`constitution.md`](dev/constitution.md),
  [`knowledge/`](dev/knowledge/),
  [`guides/`](dev/guides/),
  [`adr/`](dev/adr/)).

### Guidelines

- Project-wide non-negotiables: [`dev/constitution.md`](dev/constitution.md).
- Per-language coding standards: [`dev/guidelines/`](dev/guidelines/).
- Pre-commit hook rules: [`dev/guides/pre-commit-hooks.md`](dev/guides/pre-commit-hooks.md).
- Agent / contributor onboarding: [`AGENTS.md`](AGENTS.md).
