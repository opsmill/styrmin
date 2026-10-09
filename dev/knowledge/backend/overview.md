# Backend Architecture Overview

## Project Summary

Styrmin MVP is a **deployment orchestration platform** that manages application deployments on Kubernetes clusters. It provides a declarative approach to deploying applications through "Application Drivers" - versioned deployment specifications that define how applications should be deployed, configured, and managed.

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Web Framework** | FastAPI |
| **API** | Strawberry GraphQL |
| **ORM** | SQLModel (Pydantic + SQLAlchemy) |
| **Database** | SQLite (dev) / PostgreSQL (prod) |
| **Workflow Engine** | Prefect |
| **Kubernetes** | FluxCD v2 HelmRelease CRDs |
| **Logging** | Loguru |
| **Git Integration** | Dulwich |

## High-Level Architecture

```text
                           ┌─────────────────────────────────────┐
                           │         FastAPI Application         │
                           │      (styrmin_backend/server/)      │
                           └──────────────┬──────────────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
    ┌─────────▼─────────┐    ┌───────────▼───────────┐    ┌─────────▼─────────┐
    │     GraphQL        │    │     REST routes       │    │    Lifespan       │
    │     /graphql       │    │      /api/*           │    │   Management      │
    └─────────┬─────────┘    └───────────┬───────────┘    └───────────────────┘
              │                           │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │      Services Layer       │
              │  (Business Logic / CRUD)  │
              └─────────────┬─────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼───────┐
│  Unit of Work │  │    Prefect    │  │    Context    │
│ (Repositories)│  │    Manager    │  │   Resolver    │
└───────┬───────┘  └───────┬───────┘  └───────────────┘
        │                   │
        │          ┌───────▼───────┐
        │          │  Agent Tasks  │ ──> StyrminDeployment CRD
        │          │   (Prefect)   │     (operator reconciles)
        │          └───────────────┘
        │
┌───────▼───────┐
│   Database    │
│  (SQLModel)   │
└───────────────┘
```

The server has a single GraphQL endpoint at `/graphql`; there is no separate `/internal/graphql` mount. The kopf operator and the agent's Prefect worker run in a sibling process — see [`../agent/overview.md`](../agent/overview.md).

## Directory Structure

```text
backend/styrmin_backend/
├── server/              # Application entry point and lifecycle
│   └── app.py          # FastAPI app creation, startup/shutdown
│
├── api/                 # API layer
│   ├── schema/         # GraphQL Query and Mutation definitions
│   ├── definitions/    # GraphQL types per domain (cluster/, deployment/, task/, ...)
│   ├── rest/           # REST endpoints (legacy/internal HTTP routes)
│   ├── dependency.py   # Context injection (UnitOfWork via get_context)
│   ├── errors.py       # StructuredErrorExtension middleware
│   ├── resolvers.py    # Shared resolver helpers
│   └── scalars.py      # Custom GraphQL scalars (JSON, etc.)
│
├── db/                  # Database layer
│   ├── models.py       # SQLModel ORM models
│   ├── utils.py        # DB initialization, session management
│   └── constants.py    # Database configuration
│
├── repository/          # Data access layer
│   ├── base.py         # Abstract BaseRepository
│   └── [entity].py     # Repository per entity
│
├── services/            # Business logic layer (see services.md for the full list)
│   ├── [entity].py     # Core CRUD services
│   ├── unit_of_work.py # UnitOfWork pattern
│   ├── driver/         # Application driver parsing
│   ├── reconciliation/ # State diff and remediation
│   ├── backup/         # Backup/restore (see backup-restore.md)
│   ├── helm/           # Helm chart rendering helpers
│   ├── workflow/       # Workflow executor (Prefect wrapper)
│   ├── ingress_controller/, scheduling/, utilities/
│
├── workflows/           # Prefect workflow registry (server-side)
│   ├── manager.py      # PrefectManager (submit, register, lookup)
│   ├── catalogue.py    # Workflow registry (registers *_crd flows)
│   ├── models.py       # PrefectAction, WorkflowDefinition
│   └── templates/      # Backup/restore workflow templates
│
├── agent/               # Agent code (lives in this package but runs in the agent process)
│   ├── service/        # K8s resource builders
│   ├── tasks/          # Prefect flow definitions executed by the agent's worker
│   └── status/         # Periodic pod + CRD status reporter
│   # See dev/knowledge/agent/overview.md
│
├── operator/            # Kopf operator (runs in the agent process)
│   # See dev/knowledge/agent/operator.md
│
├── context/             # Deployment context resolution
│   ├── models/         # Context data models (GlobalContext, ChartInfo, ...)
│   ├── resolvers.py    # Context resolution logic
│   └── validators.py   # Context validation
│
├── domain/              # Domain models
│   ├── models.py       # Core business objects (Deployment, Instance, ...)
│   └── payloads.py     # Inter-module payloads
│
├── actions/             # Action primitives importable from driver actions
│   └── primitives.py   # stop_components, start_components, execute_commands
│
├── cli/                 # styrminctl CLI (Cyclopts-based)
│
├── entrypoint/          # Process entrypoints
│   └── combined.py     # Shared event loop: kopf + Prefect worker + status reporter
│
└── config.py            # Pydantic Settings (top-level module, not a package)
```

For the agent-side details (status reporter, operator, Kubernetes resource builders), see [`../agent/overview.md`](../agent/overview.md) and [`../agent/operator.md`](../agent/operator.md).

## Request Flow

```text
1. HTTP Request
      ↓
2. FastAPI Router (server/app.py)
      ↓
3. GraphQL Schema (api/schema/query.py or mutation.py)
      ↓
4. Context Injection (api/dependency.py → UnitOfWork)
      ↓
5. Service Layer (services/*.py)
      ↓
6. Repository Layer (repository/*.py)
      ↓
7. Database (db/models.py → SQLModel → DB)
```

For async operations (deployments, updates):

```text
5. Service Layer
      ↓
6. Prefect Manager (workflows/manager.py)
      ↓
7. Agent Tasks (agent/tasks/*.py)
      ↓
8. Kubernetes (FluxCD HelmRelease)
```

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| **server/** | Application bootstrap, lifecycle management |
| **api/** | GraphQL schema, types, routing, context injection |
| **db/** | ORM models, database connections |
| **repository/** | CRUD operations on domain entities |
| **services/** | Business logic, orchestration, validation |
| **workflows/** | Prefect workflow management and execution |
| **agent/** | Kubernetes resource creation via FluxCD |
| **context/** | Deployment context resolution and validation |
| **domain/** | Core domain models and business objects |
| **config/** | Configuration from environment/files |

## Key Concepts

### Application Driver

A versioned specification that defines how to deploy an application:

- Helm chart configuration
- Component definitions
- Custom actions (hooks)
- Configuration templates

### Deployment

Represents the **desired state** of an application in an environment. Tracks:

- Application version to deploy
- Configuration overrides
- Component settings
- Associated tasks

### Application Instance

The **runtime representation** of a deployed application. Created when a deployment is reconciled.

### Task

An async operation tracked by the system. `TaskType` values:

- NOOP (reconciliation produced no remediation)
- CREATE_INSTANCE, DELETE_INSTANCE
- UPDATE_INSTANCE, UPGRADE_INSTANCE
- STOP_COMPONENTS, START_COMPONENTS, RUN_JOB

### Context

A resolved set of configuration values passed to deployments, containing:

- Cluster configuration
- Environment configuration
- Deployment configuration
- Component configurations

## Entry Point

The application starts in `server/app.py`:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="OpsMill Styrmin-MVP Platform", lifespan=lifespan)
    app.include_router(init_rest_router())
    app.include_router(init_graphql_router(), prefix="/graphql")
    return app
```

Startup sequence:

1. Load configuration from `styrmin.toml` or environment
2. Initialize database (SQLite or PostgreSQL)
3. Configure logging with Loguru
4. Initialize Prefect workflow manager
5. Initialize infrastructure utilities

### Settings loading

`config.SETTINGS` (`backend/styrmin_backend/config.py`) holds the settings for the whole process, and each process parses them once:

- Entrypoints that accept `--config-file` (`styrmin server start`, `styrmin db ...`) call `SETTINGS.initialize(path)` before any code reads a setting.
- `styrmin agent start` calls `SETTINGS.initialize_and_exit()` before it imports the operator's handler modules, which read settings at import, so invalid settings print a validation summary instead of a traceback. It passes the loaded `Settings` to `entrypoint/combined.py::main`, which gives the status reporter its GraphQL URL and poll interval as arguments.
- Every other process (Prefect flow runs, Alembic) loads the settings on first access, from the file named by `STYRMIN_CONFIG` (default `styrmin.toml` in the working directory). Without that file, only environment variables and defaults apply.
- A value set in `styrmin.toml` takes precedence over its `STYRMIN_*` environment variable. A setting that the file does not set is read from the environment, then falls back to its default.
- Each section (`database`, `workflow`, `kubernetes`, `driver`, `agent_code`, `agent`, `operator`, `url`, `telemetry`) reads its environment variables when the settings load, not when the module is imported.
- `SETTINGS.initialize(path)` raises `InitializationError` when the settings were already loaded from another file, so a call made too late cannot silently ignore the requested file.
- Settings classes with aliased fields (`Settings`, `DatabaseSettings`, `KubernetesSettings`, `OperatorSettings`, `TelemetrySettings`) set `populate_by_name=True`, so `styrmin.toml` sets those fields by their field name, the name `styrmin config show` writes. A test loads the output of `styrmin config show` back as a config file.
- `styrmin config show` leaves out the fields listed in `config.SECRET_FIELDS`:
  - `admin_password`
  - `[database]` `db_password` and `db_url`, because the Helm chart builds `db_url` with the database password in it
  - the `token` field of `[kubernetes]`, `[driver]` and `[agent_code]`

  An operator who saves that output as `styrmin.toml` therefore keeps setting these credentials through the environment, and rotating a credential in the environment still takes effect. Add any new credential field to `SECRET_FIELDS`.

Read configuration through `config.SETTINGS`, not `os.environ`. `AgentSettings` holds the `STYRMIN_AGENT_POLL_*` and `STYRMIN_AGENT_STATUS_POLL_INTERVAL` settings, and `api_token`, read from `STYRMIN_TOKEN`: the reconcile's API token that Styrmin sets on the remediation and driver action jobs (ADR-059). `api_token` is left out of `styrmin config show`. `KubernetesSettings.kubeconfig` reads `KUBECONFIG`. `RemoteAgentCodeSettings` holds `STYRMIN_AGENT_SOURCE_*`. `OperatorSettings` holds `STYRMIN_OPERATOR_*`, `DELETED_CR_TTL_HOURS` and `STYRMIN_JANITOR_INTERVAL`. `TelemetrySettings` holds `STYRMIN_TELEMETRY_ENABLED`, `STYRMIN_TELEMETRY_ENDPOINT` and `DO_NOT_TRACK`; its `disabled_by()` names the setting that turned telemetry off, for the startup log line and the daily telemetry flow ([ADR-061](../../adr/0061-server-anonymous-daily-telemetry.md)). Kopf timer intervals and Prefect task retries are read when their modules are imported, so they take the values present when the agent process starts.

The agent process is a separate entrypoint (`entrypoint/combined.py`) that runs the kopf operator, the Prefect worker, and the status reporter together — see [`../agent/overview.md`](../agent/overview.md).
