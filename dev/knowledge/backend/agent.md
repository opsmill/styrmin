# Backend Agent & Workflows Documentation

## Overview

The agent module handles Kubernetes resource creation and management through Prefect workflows. It integrates with FluxCD to deploy applications using HelmRelease custom resources.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        Prefect Manager                              │
│                     (workflows/manager.py)                          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼─────┐  ┌──────▼──────┐  ┌─────▼─────┐
    │   Catalogue   │  │  Executor   │  │  Blocks   │
    │  (workflows)  │  │  (worker)   │  │  (creds)  │
    └───────────────┘  └──────┬──────┘  └───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼────┐  ┌──────▼──────┐  ┌────▼─────────┐
    │ Orchestration│  │ Application │  │    Core      │
    │    Tasks     │  │   Tasks     │  │   Tasks      │
    └──────────────┘  └─────────────┘  └──────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼────┐  ┌──────▼──────┐  ┌────▼─────────┐
    │   Resource   │  │   Blocks    │  │  Utilities   │
    │   Builders   │  │  (metadata) │  │  (ingress)   │
    └──────────────┘  └─────────────┘  └──────────────┘
                              │
                      ┌───────▼───────┐
                      │   Kubernetes  │
                      │   (FluxCD)    │
                      └───────────────┘
```

## Directory Structure

```text
styrmin_backend/
├── workflows/                    # Prefect workflow management
│   ├── manager.py               # PrefectManager - main orchestrator
│   ├── catalogue.py             # Workflow registry
│   ├── models.py                # Workflow data models
│   ├── constants.py             # WorkflowType enum
│   ├── dependency.py            # Manager dependency injection
│   └── utils.py                 # Utilities
│
└── agent/                        # Kubernetes agent
    ├── tasks/                   # Prefect task definitions
    │   ├── core.py              # Core rendering tasks
    │   ├── application.py       # Application-specific tasks
    │   ├── orchestration.py     # Main orchestration flows
    │   ├── extra.py             # Additional/experimental tasks
    │   └── shared.py            # Shared utilities
    │
    └── service/                 # Kubernetes service layer
        ├── exceptions.py
        └── kubernetes/
            ├── dependency.py    # K8s dependency injection
            ├── primitives.py    # Low-level K8s operations
            ├── utils.py         # K8s reference generation
            └── resources/       # Resource builders
                ├── custom_resource.py  # HelmRelease CRD
                ├── blocks/      # Resource block builders
                │   ├── base.py
                │   ├── metadata.py
                │   ├── spec.py
                │   └── patches.py
                ├── builders/    # High-level builders
                │   ├── base.py
                │   ├── application.py
                │   └── utility.py
                └── utilities/   # Utility implementations
                    ├── base.py
                    ├── factory.py
                    ├── ingress.py
                    └── environment.py
```

## Prefect Manager

The `PrefectManager` orchestrates workflow execution and manages Prefect resources.

### Key Methods

```python
class PrefectManager:
    async def run_action(self, action: PrefectAction, parameters: dict) -> WorkflowInfo:
        """Run a specific action workflow"""

    async def register_user_action(self, workflow, application, version, hook, mode):
        """Register a user-defined action in Prefect"""

    async def get_user_action_deployment_id(self, application, version, hook, mode) -> UUID:
        """Get deployment ID for a user action"""

    async def register_token(self, namespace: str, token: str):
        """Register GitHub credentials"""

    async def initialize(self):
        """Setup work pools, deployments, and blocks"""
```

### Workflow Types

```python
class WorkflowType(str, Enum):
    INTERNAL = "internal"  # Core system workflows
    USER = "user"          # User-defined action workflows
```

### Work Pools

```python
class PrefectWorkPool(str, Enum):
    STYRMIN_WORK_POOL = "styrmin-work-pool"  # System workflows
    USER_WORK_POOL = "user-work-pool"        # User workflows
```

### Actions

Actions are tagged for routing:

- `application/{name}` - Application name
- `version/{version}` - Application version
- `hook/{hook}` - Hook type (e.g., deploy, update)
- `mode/{mode}` - Execution mode (pre, core, post)

## Agent Tasks

### Core Tasks (`agent/tasks/core.py`)

Low-level rendering tasks:

```python
@task
def render_application_helm_release_specifications(context: GlobalContext) -> dict:
    """Render HelmRelease specification for an application"""
```

### Application Tasks (`agent/tasks/application.py`)

Application-specific orchestration:

```python
@task
def deploy_application_instance(instance: Instance) -> None:
    """Deploy a new application instance"""

@task
def update_application_instance(instance: Instance) -> None:
    """Update an existing application instance"""
```

### Orchestration Tasks (`agent/tasks/orchestration.py`)

High-level orchestration flows:

```python
@flow
def create_instance_flow(instance_id: UUID) -> None:
    """Flow to create a new instance"""

@flow
def update_instance_flow(instance_id: UUID) -> None:
    """Flow to update an instance"""

@flow
def delete_instance_flow(instance_id: UUID) -> None:
    """Flow to delete an instance"""
```

### Shared Utilities (`agent/tasks/shared.py`)

Common task utilities and helpers.

## Kubernetes Resource Building

### HelmRelease Generation

The agent generates FluxCD v2 HelmRelease CRDs for deployments:

```python
# resources/custom_resource.py
class HelmRelease:
    """FluxCD v2 HelmRelease custom resource"""
    api_version: str = "helm.toolkit.fluxcd.io/v2"
    kind: str = "HelmRelease"
    metadata: HelmReleaseMetadata
    spec: HelmReleaseSpec
```

### Resource Blocks

Modular building blocks for K8s resources:

| Block | Purpose |
|-------|---------|
| `MetadataBlock` | Name, namespace, labels, annotations |
| `SpecBlock` | HelmRelease spec (chart, values) |
| `PatchesBlock` | Strategic merge patches |

### Builders

High-level resource constructors:

```python
# builders/application.py
class ApplicationHelmReleaseBuilder:
    """Build HelmRelease for application deployments"""

    def build(self, context: GlobalContext) -> HelmRelease:
        ...

# builders/utility.py
class UtilityHelmReleaseBuilder:
    """Build HelmRelease for utility deployments"""

    def build(self, context: UtilityContext) -> HelmRelease:
        ...
```

### Utilities

Infrastructure utilities managed by the agent:

```python
# utilities/factory.py
class UtilityFactory:
    """Factory for creating utility resources"""

    def get_utility(self, kind: UtilityKind) -> BaseUtility:
        ...

# utilities/ingress.py
class IngressUtility(BaseUtility):
    """Ingress controller utility"""
```

## Combined Operator/Agent Process

<!-- Extracted from specs/001-k8s-operator and specs/001-deployment-crd on 2026-04-06 -->

The agent container runs both the Prefect worker and the kopf operator in a single async process. Both components share one event loop via `asyncio.gather()`. The kopf operator watches `StyrminDeployment` CRDs and manages all Kubernetes resources (NetworkPolicies, Secrets, HelmReleases, Services, Middlewares) while the Prefect worker continues to execute deployment flows.

Graceful shutdown is coordinated: kopf's `@kopf.on.cleanup()` handler signals an `asyncio.Event` to stop the Prefect worker. Both components stop together.

See [operator.md](operator.md) for full operator documentation, ADR-004 for the shared event loop design, and ADR-008 for the responsibility split between Prefect and the operator.

## Kubernetes Integration

### Primitives (`kubernetes/primitives.py`)

Low-level Kubernetes operations:

```python
def apply_resource(resource: dict) -> None:
    """Apply a K8s resource"""

def delete_resource(name: str, namespace: str, kind: str) -> None:
    """Delete a K8s resource"""
```

### Utils (`kubernetes/utils.py`)

Kubernetes reference generation:

```python
def generate_namespace_reference(context: GlobalContext) -> str:
    """Generate namespace name from context"""

def generate_release_reference(context: GlobalContext) -> str:
    """Generate HelmRelease name from context"""
```

## Workflow Execution Flow

```text
1. API receives deployment request
      ↓
2. Service layer creates Task and Deployment
      ↓
3. Reconciliation generates Instance
      ↓
4. PrefectManager.run_action() called
      ↓
5. Workflow submitted to Prefect
      ↓
6. Agent tasks execute:
   a. Generate GlobalContext
   b. Build HelmRelease specification
   c. Apply to Kubernetes
      ↓
7. FluxCD reconciles HelmRelease
      ↓
8. Callback updates Task status
```

## Workflow Models

### WorkflowDefinition

```python
class WorkflowDefinition(BaseModel):
    name: str
    flow: Callable
    type: WorkflowType
    tags: list[str]

    async def save(self, client: PrefectClient, work_pool: PrefectWorkPool):
        """Save workflow to Prefect as deployment"""
```

### WorkflowInfo

```python
class WorkflowInfo(BaseModel):
    flow_run_id: UUID
    deployment_id: UUID
```

## Key Files

| File | Purpose |
|------|---------|
| [workflows/manager.py](backend/styrmin_backend/workflows/manager.py) | Prefect workflow orchestration |
| [workflows/catalogue.py](backend/styrmin_backend/workflows/catalogue.py) | Workflow registry |
| [agent/tasks/core.py](backend/styrmin_backend/agent/tasks/core.py) | Core rendering tasks |
| [agent/tasks/orchestration.py](backend/styrmin_backend/agent/tasks/orchestration.py) | Orchestration flows |
| [agent/service/kubernetes/resources/custom_resource.py](backend/styrmin_backend/agent/service/kubernetes/resources/custom_resource.py) | HelmRelease CRD |
| [agent/service/kubernetes/resources/builders/application.py](backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py) | Application builder |
