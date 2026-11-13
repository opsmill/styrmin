# Styrmin

> Lifecycle management for your infrastructure automation stack.

📖 Documentation: <https://docs.styrmin.app>

Styrmin is in beta. The GraphQL API, the `styrminctl` commands and
flags, the Python SDK, and the driver format can still change between
releases, and Styrmin is not yet recommended for production-critical
workloads. See [Beta status](https://docs.styrmin.app/docs/beta-status)
for what the beta includes and its known limitations.

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
all. See [Why Styrmin?](https://docs.styrmin.app/docs/introduction/why-styrmin)
for the full positioning, and how Styrmin compares to ArgoCD, Flux, and
manual Helm.

## Quickstart

You need [Docker](https://docs.docker.com/get-docker/),
[`kubectl`](https://kubernetes.io/docs/tasks/tools/),
[`helm`](https://helm.sh/docs/intro/install/),
[`vcluster`](https://www.vcluster.com/docs/getting-started/setup), and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) on your
`PATH`. TCP port `8080` must be free on your machine. Then:

```bash
uv sync
uv run invoke build
uv run invoke start
```

When it finishes, open <http://styrmin.local.styrmin.io:8080> and log in
with `admin` / `styrmin`.

To pause the demo and keep its data, run `uv run invoke stop`. To delete
the demo and its data, run `uv run invoke destroy`.

The full walkthrough — what each step does, the lifecycle commands, and
troubleshooting — lives in the
[Quickstart guide](https://docs.styrmin.app/docs/installation/quickstart).
For a production install, see
[Installation](https://docs.styrmin.app/docs/installation).

## Documentation

| What you want | Where it lives |
|---------------|----------------|
| Why Styrmin, how it compares to ArgoCD/Flux | [Why Styrmin?](https://docs.styrmin.app/docs/introduction/why-styrmin) |
| Conceptual model and core vocabulary | [Platform overview](https://docs.styrmin.app/docs/introduction/platform-overview) |
| Install on your laptop or in a cloud | [Installation](https://docs.styrmin.app/docs/installation) |
| Write a driver | [Create a driver](https://docs.styrmin.app/docs/drivers/creating-a-driver) |
| Architecture, ingress, backups, hooks | [Concepts and architecture](https://docs.styrmin.app/docs/concepts-and-architecture) |
| `styrminctl` commands, driver API, configuration settings, `StyrminDeployment` CRD | [Reference](https://docs.styrmin.app/docs/reference) |
| What the beta includes and its known limitations | [Beta status](https://docs.styrmin.app/docs/beta-status) |
| The canonical project glossary | [`CONTEXT.md`](CONTEXT.md) |
| Decisions behind the architecture | [`dev/adr/`](dev/adr/) |
| Contributor / agent guide | [`AGENTS.md`](AGENTS.md) |

## Development

This section is for contributors to Styrmin itself.

### Setup

In addition to the Quickstart tools, you need Node.js 22 with
[`pnpm`](https://pnpm.io/installation) and
[`prek`](https://github.com/j178/prek), which runs the Git hooks.

```bash
uv sync                          # Python deps (root + workspace + dev group)
(cd frontend && pnpm install)    # frontend deps (required for codegen)
uv run invoke pre-commit-install # local pre-commit + pre-push hooks (needs prek)
```

### Common tasks

```bash
uv run invoke test               # backend tests, without the E2E tests
uv run pytest cli/tests          # styrminctl tests
uv run pytest python_sdk/tests   # Python SDK tests
(cd frontend && pnpm test)       # frontend tests
uv run invoke format lint        # format + lint everything (Python, Markdown, YAML)
uv run invoke generate           # regenerate SDK and frontend types from GraphQL
```

`uv run invoke test` includes the backend integration tests, and some of
them create a vCluster in Docker. The E2E tests in `backend/tests/e2e/`
also create their own vCluster. To run them, see
[`dev/knowledge/backend/e2e-testing.md`](dev/knowledge/backend/e2e-testing.md).

### Development stack in Docker Compose

To test backend changes without rebuilding the image, run the Styrmin
server, the task worker, and the agent in Docker Compose. The services
mount `backend/` from your checkout, and the server reloads when a file
changes. The agent connects to a local vCluster, so create the vCluster
first:

```bash
uv run invoke cluster.create cluster.connect cluster.init  # create the vCluster, install the Styrmin CRDs
uv run invoke dev.build dev.start    # build the image, start the services
uv run invoke dev.bootstrap          # create the cluster, environment, backup storage location, and driver records
```

Open <http://localhost:8000> and log in with `admin` / `styrmin`. The
Prefect UI is at <http://localhost:4200>.

This stack installs no ingress controller, no Garage, and no Velero in
the vCluster, so backups do not run on it. To test ingress or backups,
use the Quickstart demo. See
[`dev/guides/local-demo.md`](dev/guides/local-demo.md).

```bash
uv run invoke dev.stop dev.clean     # stop the services, delete their volumes
uv run invoke cluster.delete         # delete the vCluster
```

### Project layout

- [`backend/`](backend/) — Python backend (GraphQL API, Prefect
  workflows, agent, and operator).
  See [`backend/AGENTS.md`](backend/AGENTS.md).
- [`frontend/`](frontend/) — React + TypeScript SPA.
  See [`frontend/AGENTS.md`](frontend/AGENTS.md).
- [`python_sdk/`](python_sdk/) — async Python client SDK.
  See [`python_sdk/AGENTS.md`](python_sdk/AGENTS.md).
- [`cli/`](cli/) — `styrminctl` command-line client.
- [`driver/`](driver/) — bundled application drivers and the driver
  format reference.
- [`helm/`](helm/) — Helm charts for the Styrmin server
  (`helm/styrmin/`) and the agent (`helm/agent/`).
- [`tasks/`](tasks/) — Invoke tasks. List them with
  `uv run invoke --list`.
- [`docs/`](docs/) — public Docusaurus site published to
  <https://docs.styrmin.app>.
- [`specs/`](specs/) — feature specifications.
- [`changelog/`](changelog/) — towncrier news fragments for the next
  release.
- [`dev/`](dev/) — internal developer documentation
  ([`constitution.md`](dev/constitution.md),
  [`knowledge/`](dev/knowledge/),
  [`guides/`](dev/guides/),
  [`adr/`](dev/adr/)).

### Guidelines

- Project-wide non-negotiables: [`dev/constitution.md`](dev/constitution.md).
- Per-language coding standards: [`dev/guidelines/`](dev/guidelines/).
- Pre-commit hook rules: [`dev/guides/pre-commit-hooks.md`](dev/guides/pre-commit-hooks.md).
- Changelog entries, one news fragment for each user-visible change:
  [`dev/guidelines/changelog.md`](dev/guidelines/changelog.md).
- Agent / contributor onboarding: [`AGENTS.md`](AGENTS.md).
