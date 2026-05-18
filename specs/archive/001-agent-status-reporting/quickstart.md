# Quickstart: Agent Status Reporting

## Overview

This feature adds periodic pod status polling to the Styrmin agent. The agent collects pod health data from Kubernetes and reports it to the backend, where it is stored and exposed via the GraphQL API.

## Architecture

```text
+-----------------------------------------------------------+
|                   Agent (per cluster)                      |
|                                                           |
|  +--------------+  +--------------+  +--------------+    |
|  |Kopf Operator |  |Prefect Worker|  |Status Poller |    |
|  |  (existing)  |  |  (existing)  |  |   (new)      |    |
|  +--------------+  +--------------+  +------+-------+    |
|                                             |             |
|         K8s API <---------------------------+             |
|                                             |             |
+---------------------------------------------+-------------+
                                              |
                              GraphQL mutation | reportPodStatuses
                                              v
+-----------------------------------------------------------+
|                      Backend                              |
|                                                           |
|  +--------------+  +--------------+  +--------------+    |
|  | GraphQL API  |  |Service Layer |  |  Database    |    |
|  | (Strawberry) |--|              |--|  (PodStatus) |    |
|  +--------------+  +--------------+  +--------------+    |
+-----------------------------------------------------------+
```

## Key Components

### 1. Status Poller (Agent side)

- New async loop added to `asyncio.gather()` in `combined.py`
- Polls every `STYRMIN_AGENT_STATUS_POLL_INTERVAL` seconds (default: 60)
- Queries backend for active deployments to discover namespaces
- Lists pods in each namespace via `CoreV1Api.list_namespaced_pod()`
- Reports batch of pod statuses via `reportPodStatuses` GraphQL mutation
- Respects the existing `_shutdown` event for graceful shutdown

### 2. PodStatus Model (Backend)

- New SQLModel table linked to Deployment via FK
- Upsert semantics on (deployment_id, pod_name)
- Cascade delete when Deployment is removed
- Stores: phase, readiness, restart count, container statuses, last polled timestamp

### 3. GraphQL API (Backend)

- **Query**: `podStatuses(deploymentId, environmentId, clusterId)` — filter by scope
- **Resolver**: `Deployment.podStatuses` — nested field on existing type
- **Mutation**: `reportPodStatuses(reports)` — batch upsert from agent

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `STYRMIN_AGENT_STATUS_POLL_INTERVAL` | `60` | Polling interval in seconds |

## Development Flow

1. Add `PodStatus` model and Alembic migration
2. Add repository and service layer
3. Add `reportPodStatuses` mutation + `.graphql` query file
4. Add `podStatuses` query + `Deployment.podStatuses` resolver
5. Add status polling loop in agent entrypoint
6. Add K8s `list_pods()` primitive
7. Regenerate schema and SDK types
8. Write tests (unit + integration)
