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
    │   Public GraphQL   │    │   Internal GraphQL    │    │    Lifespan       │
    │    /graphql        │    │  /internal/graphql    │    │   Management      │
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
        │          │  Agent Tasks  │
        │          │ (Kubernetes)  │
        │          └───────────────┘
        │
┌───────▼───────┐
│   Database    │
│  (SQLModel)   │
└───────────────┘
```

## Directory Structure

```text
backend/styrmin_backend/
├── server/              # Application entry point and lifecycle
│   └── app.py          # FastAPI app creation, startup/shutdown
│
├── api/                 # GraphQL API layer
│   ├── schema/         # Query and Mutation definitions
│   ├── definitions/    # GraphQL types by domain
│   ├── fragments/      # Reusable response types
│   ├── dependency.py   # Context injection (UnitOfWork)
│   └── scalars.py      # Custom GraphQL scalars (JSON)
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
├── services/            # Business logic layer
│   ├── [entity].py     # Core CRUD services
│   ├── unit_of_work.py # UnitOfWork pattern
│   ├── driver/         # Application driver parsing
│   ├── reconciliation/ # State diff and remediation
│   ├── helm/           # Helm chart rendering
│   ├── workflow/       # Workflow execution
│   └── utilities/      # Infrastructure utilities
│
├── workflows/           # Prefect workflow management
│   ├── manager.py      # PrefectManager
│   ├── catalogue.py    # Workflow registry
│   └── models.py       # Workflow data models
│
├── agent/               # Kubernetes agent
│   ├── service/        # K8s resource builders
│   └── tasks/          # Prefect task definitions
│
├── context/             # Deployment context resolution
│   ├── models/         # Context data models
│   ├── resolvers.py    # Context resolution logic
│   └── validators.py   # Context validation
│
├── domain/              # Domain models
│   ├── models.py       # Core business objects
│   └── payloads.py     # Inter-module payloads
│
├── actions/             # Action primitives
│   └── primitives.py
│
└── config/              # Configuration
    └── config.py       # Pydantic Settings
```

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

An async operation tracked by the system:

- DEPLOYMENT, CREATE_INSTANCE, DELETE_INSTANCE
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
    app.include_router(init_graphql_router(), prefix="/graphql")
    app.include_router(init_internal_graphql_router(), prefix="/internal/graphql")
    return app
```

Startup sequence:

1. Load configuration from `styrmin.toml` or environment
2. Initialize database (SQLite or PostgreSQL)
3. Configure logging with Loguru
4. Initialize Prefect workflow manager
5. Initialize infrastructure utilities
