# Contracts: TanStack Form Migration

No API contracts change in this migration. This is a frontend-only library swap.

## Preserved Contracts

All existing GraphQL mutation contracts remain unchanged:

| Form | Mutation | Variables Shape |
|------|----------|----------------|
| AddDriverPage (local) | `LoadLocalDriver` | `{ path: string }` |
| AddDriverPage (remote) | `LoadRemoteDriver` | `{ repositoryUrl: string, branch: string }` |
| CreateBSLDialog | `CreateBackupStorageLocation` | `{ name, endpoint, bucket, region, accessKeyId, secretAccessKey }` |
| BSLDetailPage | `UpdateBackupStorageLocation` | `{ backupStorageLocationId, accessKeyId, secretAccessKey }` |
| BSLDetailPage | `DeleteBackupStorageLocation` | `{ backupStorageLocationId }` |
| DeployFormPage | `Deploy` | `{ driver, name, version, environmentId, parameters }` |
| CreateClusterDialog | `CreateCluster` | `{ name, config: ClusterConfig }` |
| CreateEnvironmentDialog | `CreateEnvironment` | `{ name, clusterId, config: EnvironmentConfig }` |

The form library migration does not modify the shape of any mutation variables. The `buildClusterConfig()` and `buildEnvironmentConfig()` helper functions that transform form values into nested config objects also remain unchanged.
