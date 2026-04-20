# Quickstart: Delete Deployments

Exercise the delete-deployment feature end-to-end on a local
Kind-based Styrmin environment.

## Prerequisites

- Local Kind cluster with Styrmin backend, Prefect, FluxCD, and the
  Styrmin operator running (standard `dev/` setup).
- A driver installed and at least one deployment created. Reuse the
  existing dev e2e fixtures or create a deployment via the UI.

## Backend-only smoke test (GraphQL)

1. Identify a target deployment.

   ```graphql
   query {
     environments {
       id
       name
       deployments {
         id
         name
         status
       }
     }
   }
   ```

2. Request deletion, retaining backups.

   ```graphql
   mutation {
     deleteDeployment(
       deploymentId: "<uuid>"
       backupDisposition: RETAIN
     ) {
       id
       type       # => DELETE_INSTANCE
       status     # => PENDING or RUNNING
     }
   }
   ```

3. Poll deployment state.

   ```graphql
   query ($id: UUID!) {
     deployment(id: $id) {
       id
       status     # DELETION_REQUESTED → DELETION_IN_PROGRESS → DELETED
       deletedAt
     }
   }
   ```

4. After `status == DELETED`, confirm cluster state:

   ```bash
   kubectl get styrmindeployment --all-namespaces
   kubectl get helmrelease --all-namespaces
   kubectl get ns | grep <deployment-namespace>
   ```

   All objects owned by the deployment should be gone. The
   `Deployment` record remains fetchable by id, with its full
   timeline, in `DELETED` state.

5. Verify backup retention. Fetch backups for the (now tombstoned)
   deployment — they must still be listable and restorable.

## Full UI flow

1. Visit the deployment detail page for the target deployment.
2. Click **Delete** in the actions area.
3. In the confirmation dialog:
   - Verify the deployment name is shown.
   - Choose **Retain backups** or **Remove backups**.
   - Click **Delete**.
4. The page enters an "in-progress deletion" banner state. The
   timeline acquires a `DELETE_INSTANCE` entry, transitioning from
   PENDING → RUNNING.
5. Once teardown completes, the UI navigates to the parent
   environment detail page. Navigating back to the deployment URL
   shows a tombstoned read-only view.

## Concurrency guard

Try deleting while another workflow is in flight (e.g., immediately
after clicking Upgrade). The mutation should reject with
`extensions.code == "DEPLOYMENT_MUTATION_IN_PROGRESS"` and the UI
should surface an actionable toast without navigating.

## Backup REMOVE path

1. Ensure the deployment has at least one COMPLETED backup.
2. Trigger delete with `backupDisposition: REMOVE`.
3. Observe the Task parameters (on the timeline entry) show
   `backup_disposition: REMOVE`.
4. After teardown, the backups must no longer be listable and must
   be absent from backup storage.

## Idempotency

Re-issue the same mutation for a deployment in a deletion lifecycle
state. The API must return `DEPLOYMENT_ALREADY_DELETED` rather than
initiating a second teardown.
