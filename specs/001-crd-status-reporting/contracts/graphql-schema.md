# GraphQL Contract: CRD Status Reporting

## New Types

```graphql
type CrdCondition {
  type: String!
  status: String!
  reason: String
  message: String
  lastTransitionTime: DateTime
}

type ManagedResourceCounts {
  networkPolicies: Int!
  secrets: Int!
  helmReleases: Int!
  services: Int!
  middlewares: Int!
}

type DeploymentCrdStatus {
  id: UUID!
  deploymentId: UUID!
  phase: String!
  message: String
  conditions: [CrdCondition!]!
  managedResourceCounts: ManagedResourceCounts
  lastPolledAt: DateTime!
  createdOn: DateTime!
  updatedOn: DateTime!
}
```

## Extended Types

```graphql
extend type Deployment {
  """Latest StyrminDeployment CRD status for this deployment."""
  crdStatus: DeploymentCrdStatus
}
```

## New Mutations (Internal -- used by agents)

```graphql
input CrdConditionInput {
  type: String!
  status: String!
  reason: String
  message: String
  lastTransitionTime: DateTime
}

input ManagedResourceCountsInput {
  networkPolicies: Int!
  secrets: Int!
  helmReleases: Int!
  services: Int!
  middlewares: Int!
}

input DeploymentCrdStatusReport {
  deploymentId: UUID!
  phase: String!
  message: String
  conditions: [CrdConditionInput!]
  managedResourceCounts: ManagedResourceCountsInput
}

extend type Mutation {
  """
  Report CRD statuses for one or more deployments.
  Called by the agent on each poll cycle.
  Upserts CRD status and updates Deployment status based on phase mapping.
  """
  reportCrdStatuses(
    reports: [DeploymentCrdStatusReport!]!
  ): ReportCrdStatusesResponse!
}

type ReportCrdStatusesResponse {
  success: Boolean!
  message: String!
  statusesUpdated: Int!
  deploymentsUpdated: Int!
}
```

## Query Examples

### Get deployment with CRD status

```graphql
query GetDeploymentCrdStatus($deploymentId: UUID!) {
  deployment(deploymentId: $deploymentId) {
    name
    status
    crdStatus {
      phase
      message
      conditions {
        type
        status
        reason
        message
        lastTransitionTime
      }
      managedResourceCounts {
        networkPolicies
        secrets
        helmReleases
        services
        middlewares
      }
      lastPolledAt
    }
  }
}
```

### Agent reports CRD statuses

```graphql
mutation ReportCrdStatuses($reports: [DeploymentCrdStatusReport!]!) {
  reportCrdStatuses(reports: $reports) {
    success
    message
    statusesUpdated
    deploymentsUpdated
  }
}
```
