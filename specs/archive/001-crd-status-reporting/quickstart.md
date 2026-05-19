# Quickstart: CRD Status Reporting

## Overview

This feature extends the existing status reporting agent to also collect StyrminDeployment CRD status and use it to keep the Deployment status in sync with the actual cluster state.

## Architecture

```text
+-----------------------------------------------------------+
|                   Agent (per cluster)                      |
|                                                           |
|  Status Poller (existing loop)                            |
|  +------------------------------------------------------+ |
|  | 1. Fetch active deployments from backend              | |
|  | 2. For each deployment:                               | |
|  |    a. List pods (existing)                            | |
|  |    b. Read StyrminDeployment CRD status (NEW)         | |
|  | 3. Report pod statuses (existing mutation)            | |
|  | 4. Report CRD statuses (NEW mutation)                 | |
|  +------------------------------------------------------+ |
|         K8s API <--- get_custom_resource()                 |
+---------------------------------------------+-------------+
                                              |
                        GraphQL mutations     |
                        reportPodStatuses     |
                        reportCrdStatuses     |
                                              v
+-----------------------------------------------------------+
|                      Backend                              |
|                                                           |
|  reportCrdStatuses mutation                               |
|  +------------------------------------------------------+ |
|  | 1. Upsert DeploymentCrdStatus record                  | |
|  | 2. Map CRD phase -> DeploymentStatus                  | |
|  | 3. Update Deployment.status if changed                | |
|  +------------------------------------------------------+ |
+-----------------------------------------------------------+
```

## Key Components

### 1. Agent CRD Collection (reporter.py extension)

- Read StyrminDeployment CRD via `get_custom_resource()` for each deployment
- CRD name = namespace = `styrmin-{deployment_id}`
- Extract: phase, conditions, managed_resources, message
- Handle missing CRD (404) gracefully — skip deployment

### 2. DeploymentCrdStatus Model (Backend)

- New SQLModel table: one record per deployment (unique on deployment_id)
- Stores: phase (string), conditions (JSON), managed_resource_counts (JSON), message, last_polled_at
- Cascade delete when Deployment removed

### 3. Deployment Status Sync (Backend Service)

- CRD phase mapping: Pending/Creating* -> `pending`, Ready -> `running`, Failed -> `failed`, Deleting -> no change
- Updates Deployment.status in the same transaction as CRD status upsert

### 4. GraphQL API

- **Query**: `Deployment.crdStatus` — nested resolver on existing type
- **Mutation**: `reportCrdStatuses` — batch upsert + Deployment status sync

## Development Flow

1. Add `DeploymentCrdStatus` model and Alembic migration
2. Add repository and service layer (including Deployment status mapping)
3. Add `reportCrdStatuses` mutation + `.graphql` query file
4. Add `Deployment.crdStatus` resolver
5. Extend status reporter to collect CRD status via `get_custom_resource()`
6. Regenerate schema and SDK types
7. Write tests
