# Research: Deployment History Timeline

**Date**: 2026-04-03  
**Feature**: 001-deployment-history-timeline

## R1: Task Timestamp Exposure in GraphQL

**Decision**: Add `created_on` and `updated_on` fields to the GraphQL `Task` type.

**Rationale**: The database model (`StyrminModel` base class) already stores `created_on` (server-default `now()`) and `updated_on` (server-default `now()`, onupdate `now()`) as timezone-aware datetimes. They just aren't mapped to the Strawberry GraphQL type in `backend/styrmin_backend/api/definitions/task/model.py`. Adding two `datetime` fields to the Strawberry type and including them in `from_instance()` is all that's needed.

**Alternatives considered**:
- Adding separate audit fields: Unnecessary — base model already provides them.
- Using Prefect timestamps instead: Would couple to orchestration layer and miss non-Prefect tasks.

## R2: Querying Tasks by Deployment

**Decision**: Add a `find_by_deployment` repository method and a `tasksByDeployment(deploymentId)` GraphQL query returning tasks ordered by `created_on DESC`.

**Rationale**: The `Task` model has a `deployment_id` foreign key. The repository layer already follows the pattern of custom finder methods (e.g., `find_names_with_prefix`, `find_internal_by_environment`). Adding `find_by_deployment(deployment_id)` with a `select().where().order_by(desc(created_on))` follows established conventions. A new GraphQL query field is needed since the existing `tasks()` query returns all tasks globally with no filtering.

**Alternatives considered**:
- Adding tasks as a nested resolver on Deployment type: Would work but a top-level query is more flexible for pagination and independent fetching. Could add both — nested resolver for convenience, query for advanced use.
- Filtering via the existing `tasks()` query with optional `deploymentId` parameter: Viable but the existing query has no filtering support; a dedicated query is cleaner and follows the `backups(instanceId)` pattern.

## R3: Application Version per Task

**Decision**: Retrieve version from the `ApplicationInstance` associated with the deployment at the time of each task. The approach is to include `application_version` on the task's related deployment or join through `application_instances` ordered by time.

**Rationale**: Tasks don't directly store `application_version`. However, `Deployment.application_version` reflects the *current* desired version, and `ApplicationInstance.application_version` captures the version at instance creation time. For the timeline, the most accurate approach is: for each task, look at the `ApplicationInstance` that was active at that point. Since `ApplicationInstance` records are historical (deployment has `application_instances: list[ApplicationInstance]`), we can correlate by timestamp or by the active instance at task completion time.

**Alternatives considered**:
- Storing `application_version` directly on Task: Would require a schema change and backfill. Deferred — can be added later if the join approach is too slow.
- Using only `Deployment.application_version`: Would show current version for all tasks, losing historical accuracy.

## R4: Context Diff Strategy

**Decision**: Compare `ApplicationInstance.context` (JSON dict) between consecutive operations by diffing the two JSON objects. Compute diffs on the backend and return structured change data.

**Rationale**: The user specified that context diffs are the preferred approach for change tracking. `ApplicationInstance.context` stores the full `GlobalContext` as a serialized JSON dict containing cluster, environment, deployment, instance, app, labels, components, utilities, parameters, services, and deployed_services. Comparing two context dicts produces a comprehensive change summary. Backend computation avoids sending two full context objects to the frontend.

**Alternatives considered**:
- Frontend-side diffing: Would require sending full context payloads for adjacent tasks; increases payload size.
- Storing explicit changelogs: Requires new schema and write-path changes; overkill for v1.
- Text-based diff (like unified diff): Less structured; JSON object diff provides typed additions/removals/modifications.

## R5: Pagination Strategy

**Decision**: No pagination for v1. Return all tasks for a deployment in a single query. Add pagination later if deployments regularly exceed 100 tasks.

**Rationale**: Deployments are unlikely to have more than ~50 tasks in typical usage. The `backups()` and other existing queries also return full lists without pagination. Adding pagination now would require new patterns (cursor-based or offset) that don't exist in the codebase yet. The spec's FR-008 (handle 100+ entries) can be addressed with frontend virtual scrolling if needed.

**Alternatives considered**:
- Cursor-based pagination from the start: Over-engineering for v1 given typical data volumes.
- Offset pagination: Simpler but still adds unnecessary complexity at this stage.

## R6: Frontend Component Approach

**Decision**: Add a new "History" section to the existing `DeploymentDetailPage` using the same Card/Collapsible patterns already used for backups and restores.

**Rationale**: The deployment detail page already has a pattern for displaying hierarchical timeline data (backups → restores → component statuses) using Radix UI Collapsible components. The history timeline can follow the same pattern: each task as a row with an expandable section showing the context diff. This maintains UI consistency and avoids introducing new component patterns.

**Alternatives considered**:
- Separate tab/page for history: Adds navigation overhead; the detail page already consolidates deployment info.
- Dedicated timeline component library: Over-engineering; the existing Collapsible + Card pattern is sufficient.

## R7: GraphQL Schema Governance Gate

**Decision**: This feature requires GraphQL schema modifications (new fields on Task, new query). This is a governance gate item per the constitution.

**Rationale**: The constitution lists "GraphQL schema modifications" as requiring explicit discussion. The changes are: (1) adding `createdOn`/`updatedOn` to Task type, (2) adding `tasksByDeployment` query, (3) potentially adding a `context` field or diff resolver. These are additive-only changes (no breaking changes).

**Alternatives considered**: N/A — governance gate is mandatory.
