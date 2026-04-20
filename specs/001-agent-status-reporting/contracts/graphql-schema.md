# GraphQL Contract: Agent Status Reporting

## New Types

```graphql
enum PodPhase {
  PENDING
  RUNNING
  SUCCEEDED
  FAILED
  UNKNOWN
}

type ContainerStatus {
  name: String!
  ready: Boolean!
  state: String!
  restartCount: Int!
  image: String!
  startedAt: DateTime
}

type PodStatus {
  id: UUID!
  deploymentId: UUID!
  podName: String!
  namespace: String!
  phase: PodPhase!
  ready: Boolean!
  restartCount: Int!
  containerStatuses: [ContainerStatus!]
  nodeName: String
  startedAt: DateTime
  lastPolledAt: DateTime!
  createdOn: DateTime!
  updatedOn: DateTime!
}
```

## Extended Types

```graphql
extend type Deployment {
  """Latest pod status snapshots for this deployment."""
  podStatuses: [PodStatus!]!
}
```

## New Queries

```graphql
extend type Query {
  """
  Get pod statuses with optional filtering.
  At least one filter must be provided.
  """
  podStatuses(
    deploymentId: UUID
    environmentId: UUID
    clusterId: UUID
  ): [PodStatus!]!
}
```

## New Mutations (Internal -- used by agents)

```graphql
input PodStatusInput {
  podName: String!
  namespace: String!
  phase: PodPhase!
  ready: Boolean!
  restartCount: Int!
  containerStatuses: JSON
  nodeName: String
  startedAt: DateTime
}

input DeploymentPodStatusReport {
  deploymentId: UUID!
  pods: [PodStatusInput!]!
}

extend type Mutation {
  """
  Report pod statuses for one or more deployments.
  Called by the agent on each poll cycle.
  Upserts pod records and removes pods no longer present.
  """
  reportPodStatuses(
    reports: [DeploymentPodStatusReport!]!
  ): ReportPodStatusesResponse!
}

type ReportPodStatusesResponse {
  success: Boolean!
  message: String!
  podsUpdated: Int!
  podsRemoved: Int!
}
```

## Query Examples

### Get pod statuses for a specific deployment

```graphql
query GetDeploymentPodStatuses($deploymentId: UUID!) {
  deployment(deploymentId: $deploymentId) {
    name
    status
    podStatuses {
      podName
      phase
      ready
      restartCount
      containerStatuses {
        name
        ready
        state
        restartCount
      }
      lastPolledAt
    }
  }
}
```

### Get all pod statuses in an environment

```graphql
query GetEnvironmentPodStatuses($environmentId: UUID!) {
  podStatuses(environmentId: $environmentId) {
    deploymentId
    podName
    phase
    ready
    restartCount
    lastPolledAt
  }
}
```

### Agent reports pod statuses (mutation)

```graphql
mutation ReportPodStatuses($reports: [DeploymentPodStatusReport!]!) {
  reportPodStatuses(reports: $reports) {
    success
    message
    podsUpdated
    podsRemoved
  }
}
```
