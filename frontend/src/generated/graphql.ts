import gql from 'graphql-tag';
import * as Urql from 'urql';
export type Maybe<T> = T | null;
export type InputMaybe<T> = Maybe<T>;
export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };
export type MakeOptional<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]?: Maybe<T[SubKey]> };
export type MakeMaybe<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]: Maybe<T[SubKey]> };
export type MakeEmpty<T extends { [key: string]: unknown }, K extends keyof T> = { [_ in K]?: never };
export type Incremental<T> = T | { [P in keyof T]?: P extends ' $fragmentName' | '__typename' ? T[P] : never };
export type Omit<T, K extends keyof T> = Pick<T, Exclude<keyof T, K>>;
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string; }
  String: { input: string; output: string; }
  Boolean: { input: boolean; output: boolean; }
  Int: { input: number; output: number; }
  Float: { input: number; output: number; }
  /** Date with time (isoformat) */
  DateTime: { input: any; output: any; }
  /** The `JSON` scalar type represents JSON values as specified by ECMA-404 */
  JSON: { input: Record<string, unknown>; output: Record<string, unknown>; }
  UUID: { input: string; output: string; }
};

export type Action = {
  __typename?: 'Action';
  description: Scalars['String']['output'];
  id: Scalars['UUID']['output'];
  image?: Maybe<Scalars['String']['output']>;
  location: Scalars['String']['output'];
  name: Scalars['String']['output'];
};

export type ApplicationDriver = {
  __typename?: 'ApplicationDriver';
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  versions: Array<ApplicationDriverVersion>;
};

export type ApplicationDriverVersion = {
  __typename?: 'ApplicationDriverVersion';
  actions: Array<Action>;
  applicationDriverId: Scalars['UUID']['output'];
  componentConfigs: Array<ComponentConfig>;
  components?: Maybe<Scalars['JSON']['output']>;
  defaultVersion?: Maybe<Scalars['String']['output']>;
  helmChart: HelmChart;
  id: Scalars['UUID']['output'];
  parameters: Array<ParameterDefinition>;
  services: Array<ServiceDefinition>;
  sourceBranch?: Maybe<Scalars['String']['output']>;
  sourcePath?: Maybe<Scalars['String']['output']>;
  sourceRepository: Scalars['String']['output'];
  sourceType: Scalars['String']['output'];
  supportedVersions: Scalars['String']['output'];
  version: Scalars['String']['output'];
};

export type ApplicationInstance = {
  __typename?: 'ApplicationInstance';
  applicationDriverVersionId: Scalars['UUID']['output'];
  applicationVersion: Scalars['String']['output'];
  deploymentId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  status: Scalars['String']['output'];
};

export type Backup = {
  __typename?: 'Backup';
  completedAt?: Maybe<Scalars['DateTime']['output']>;
  componentStatuses?: Maybe<Array<ComponentBackupStatus>>;
  createdOn: Scalars['DateTime']['output'];
  errorMessage?: Maybe<Scalars['String']['output']>;
  id: Scalars['UUID']['output'];
  instanceId: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  sizeBytes?: Maybe<Scalars['Int']['output']>;
  startedAt?: Maybe<Scalars['DateTime']['output']>;
  status: Scalars['String']['output'];
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

export type BackupSchedule = {
  __typename?: 'BackupSchedule';
  createdOn: Scalars['DateTime']['output'];
  cronExpression: Scalars['String']['output'];
  deploymentId: Scalars['UUID']['output'];
  enabled: Scalars['Boolean']['output'];
  id: Scalars['UUID']['output'];
  lastBackupAt?: Maybe<Scalars['DateTime']['output']>;
  name: Scalars['String']['output'];
  nextBackupAt?: Maybe<Scalars['DateTime']['output']>;
  prefectDeploymentId?: Maybe<Scalars['UUID']['output']>;
  retentionCount: Scalars['Int']['output'];
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

export type BackupStorageLocation = {
  __typename?: 'BackupStorageLocation';
  bucket: Scalars['String']['output'];
  createdOn: Scalars['DateTime']['output'];
  endpoint: Scalars['String']['output'];
  environmentCount: Scalars['Int']['output'];
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  region: Scalars['String']['output'];
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

export type BackupStorageLocationAlreadyExists = {
  __typename?: 'BackupStorageLocationAlreadyExists';
  existingId: Scalars['UUID']['output'];
  message: Scalars['String']['output'];
};

export type BackupStorageLocationInUse = {
  __typename?: 'BackupStorageLocationInUse';
  environmentNames: Array<Scalars['String']['output']>;
  message: Scalars['String']['output'];
};

export type BackupStorageLocationNotFound = {
  __typename?: 'BackupStorageLocationNotFound';
  backupStorageLocationId: Scalars['UUID']['output'];
  message: Scalars['String']['output'];
};

export type CallbackResponse = {
  __typename?: 'CallbackResponse';
  message: Scalars['String']['output'];
  success: Scalars['Boolean']['output'];
};

export type Cluster = {
  __typename?: 'Cluster';
  config: Scalars['JSON']['output'];
  createdOn: Scalars['DateTime']['output'];
  environments: Array<Environment>;
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

export type Component = {
  __typename?: 'Component';
  enabled: Scalars['Boolean']['output'];
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
};

export type ComponentBackupStatus = {
  __typename?: 'ComponentBackupStatus';
  componentName: Scalars['String']['output'];
  errorMessage?: Maybe<Scalars['String']['output']>;
  sizeBytes?: Maybe<Scalars['Int']['output']>;
  status: Scalars['String']['output'];
};

export type ComponentConfig = {
  __typename?: 'ComponentConfig';
  config?: Maybe<Scalars['JSON']['output']>;
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
};

export type ComponentRestoreStatus = {
  __typename?: 'ComponentRestoreStatus';
  componentName: Scalars['String']['output'];
  errorMessage?: Maybe<Scalars['String']['output']>;
  status: Scalars['String']['output'];
};

export type CreateBackupStorageLocationResult = BackupStorageLocation | BackupStorageLocationAlreadyExists;

export type DeleteBackupStorageLocationResult = BackupStorageLocationInUse | DeleteSuccess;

export type DeleteSuccess = {
  __typename?: 'DeleteSuccess';
  success: Scalars['Boolean']['output'];
};

export type DeployedService = {
  __typename?: 'DeployedService';
  component: Scalars['String']['output'];
  deploymentId: Scalars['UUID']['output'];
  driverServiceName: Scalars['String']['output'];
  id: Scalars['UUID']['output'];
  kind: Scalars['String']['output'];
  port: Scalars['Int']['output'];
  resolvedName: Scalars['String']['output'];
  scope: Scalars['String']['output'];
};

export type Deployment = {
  __typename?: 'Deployment';
  applicationDriverVersionId: Scalars['UUID']['output'];
  applicationInstance?: Maybe<ApplicationInstance>;
  applicationVersion: Scalars['String']['output'];
  components: Array<Component>;
  config: Scalars['JSON']['output'];
  deployedServices: Array<DeployedService>;
  environmentId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  internal: Scalars['Boolean']['output'];
  name: Scalars['String']['output'];
  parameters: Scalars['JSON']['output'];
  status: Scalars['String']['output'];
};

export type Environment = {
  __typename?: 'Environment';
  backupStorageLocation?: Maybe<BackupStorageLocation>;
  cluster: Cluster;
  config: Scalars['JSON']['output'];
  deployments: Array<Deployment>;
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
};

export type HelmChart = {
  __typename?: 'HelmChart';
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  repository: Scalars['String']['output'];
  valueTemplate: Scalars['String']['output'];
  version: Scalars['String']['output'];
};

export type Mutation = {
  __typename?: 'Mutation';
  assignBackupStorageLocation?: Maybe<Environment>;
  callback: CallbackResponse;
  createBackup?: Maybe<Backup>;
  createBackupSchedule?: Maybe<BackupSchedule>;
  createBackupStorageLocation: CreateBackupStorageLocationResult;
  createCluster?: Maybe<Cluster>;
  createEnvironment?: Maybe<Environment>;
  createRestore?: Maybe<Restore>;
  deleteBackup?: Maybe<Scalars['String']['output']>;
  deleteBackupSchedule?: Maybe<Scalars['String']['output']>;
  deleteBackupStorageLocation: DeleteBackupStorageLocationResult;
  deleteCluster?: Maybe<Scalars['String']['output']>;
  deleteEnvironment?: Maybe<Scalars['String']['output']>;
  deploy?: Maybe<Task>;
  loadLocalApplicationDriverVersion?: Maybe<ApplicationDriverVersion>;
  loadRemoteApplicationDriverVersion?: Maybe<ApplicationDriverVersion>;
  runJob?: Maybe<Task>;
  startComponents?: Maybe<Task>;
  stopComponents?: Maybe<Task>;
  unassignBackupStorageLocation?: Maybe<Environment>;
  updateBackupSchedule?: Maybe<BackupSchedule>;
  updateBackupStorageLocation: UpdateBackupStorageLocationResult;
  updateDeployment?: Maybe<Task>;
  updateDeploymentVersion?: Maybe<Task>;
};


export type MutationAssignBackupStorageLocationArgs = {
  backupStorageLocationId: Scalars['UUID']['input'];
  environmentId: Scalars['UUID']['input'];
};


export type MutationCallbackArgs = {
  stateMessage?: InputMaybe<Scalars['String']['input']>;
  stateName: Scalars['String']['input'];
  stateType: Scalars['String']['input'];
  taskId: Scalars['UUID']['input'];
};


export type MutationCreateBackupArgs = {
  instanceId: Scalars['UUID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
};


export type MutationCreateBackupScheduleArgs = {
  cronExpression: Scalars['String']['input'];
  deploymentId: Scalars['UUID']['input'];
  enabled?: Scalars['Boolean']['input'];
  name: Scalars['String']['input'];
  retentionCount?: Scalars['Int']['input'];
};


export type MutationCreateBackupStorageLocationArgs = {
  accessKeyId: Scalars['String']['input'];
  bucket: Scalars['String']['input'];
  endpoint: Scalars['String']['input'];
  name: Scalars['String']['input'];
  region: Scalars['String']['input'];
  secretAccessKey: Scalars['String']['input'];
};


export type MutationCreateClusterArgs = {
  config?: InputMaybe<Scalars['JSON']['input']>;
  name: Scalars['String']['input'];
};


export type MutationCreateEnvironmentArgs = {
  clusterId: Scalars['UUID']['input'];
  config?: InputMaybe<Scalars['JSON']['input']>;
  name: Scalars['String']['input'];
};


export type MutationCreateRestoreArgs = {
  backupId: Scalars['UUID']['input'];
  targetInstanceId?: InputMaybe<Scalars['UUID']['input']>;
  targetNamespace: Scalars['String']['input'];
};


export type MutationDeleteBackupArgs = {
  backupId: Scalars['UUID']['input'];
};


export type MutationDeleteBackupScheduleArgs = {
  scheduleId: Scalars['UUID']['input'];
};


export type MutationDeleteBackupStorageLocationArgs = {
  backupStorageLocationId: Scalars['UUID']['input'];
};


export type MutationDeleteClusterArgs = {
  clusterId: Scalars['UUID']['input'];
};


export type MutationDeleteEnvironmentArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type MutationDeployArgs = {
  config?: InputMaybe<Scalars['JSON']['input']>;
  driver: Scalars['String']['input'];
  environmentId: Scalars['UUID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  parameters?: InputMaybe<Scalars['JSON']['input']>;
  serviceNameOverrides?: InputMaybe<Array<ServiceNameOverride>>;
  version?: InputMaybe<Scalars['String']['input']>;
};


export type MutationLoadLocalApplicationDriverVersionArgs = {
  path: Scalars['String']['input'];
};


export type MutationLoadRemoteApplicationDriverVersionArgs = {
  branch: Scalars['String']['input'];
  repositoryUrl: Scalars['String']['input'];
};


export type MutationRunJobArgs = {
  commands: Array<Scalars['String']['input']>;
  deploymentId: Scalars['UUID']['input'];
  env: Scalars['JSON']['input'];
  image: Scalars['String']['input'];
};


export type MutationStartComponentsArgs = {
  components: Array<Scalars['String']['input']>;
  deploymentId: Scalars['UUID']['input'];
};


export type MutationStopComponentsArgs = {
  components: Array<Scalars['String']['input']>;
  deploymentId: Scalars['UUID']['input'];
};


export type MutationUnassignBackupStorageLocationArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type MutationUpdateBackupScheduleArgs = {
  cronExpression?: InputMaybe<Scalars['String']['input']>;
  enabled?: InputMaybe<Scalars['Boolean']['input']>;
  name?: InputMaybe<Scalars['String']['input']>;
  retentionCount?: InputMaybe<Scalars['Int']['input']>;
  scheduleId: Scalars['UUID']['input'];
};


export type MutationUpdateBackupStorageLocationArgs = {
  accessKeyId?: InputMaybe<Scalars['String']['input']>;
  backupStorageLocationId: Scalars['UUID']['input'];
  bucket?: InputMaybe<Scalars['String']['input']>;
  endpoint?: InputMaybe<Scalars['String']['input']>;
  name?: InputMaybe<Scalars['String']['input']>;
  region?: InputMaybe<Scalars['String']['input']>;
  secretAccessKey?: InputMaybe<Scalars['String']['input']>;
};


export type MutationUpdateDeploymentArgs = {
  config?: InputMaybe<Scalars['JSON']['input']>;
  deploymentId: Scalars['UUID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  parameters?: InputMaybe<Scalars['JSON']['input']>;
  serviceNameOverrides?: InputMaybe<Array<ServiceNameOverride>>;
};


export type MutationUpdateDeploymentVersionArgs = {
  deploymentId: Scalars['UUID']['input'];
  parameters?: InputMaybe<Scalars['JSON']['input']>;
  version: Scalars['String']['input'];
};

export type ParameterDefinition = {
  __typename?: 'ParameterDefinition';
  default?: Maybe<Scalars['JSON']['output']>;
  kind: Scalars['String']['output'];
  label: Scalars['String']['output'];
  name: Scalars['String']['output'];
  values?: Maybe<Array<Scalars['String']['output']>>;
};

export type Query = {
  __typename?: 'Query';
  applicationDriver?: Maybe<ApplicationDriver>;
  applicationDrivers: Array<ApplicationDriver>;
  backup?: Maybe<Backup>;
  backupSchedule?: Maybe<BackupSchedule>;
  backupSchedules: Array<BackupSchedule>;
  backupStorageLocation?: Maybe<BackupStorageLocation>;
  backupStorageLocations: Array<BackupStorageLocation>;
  backups: Array<Backup>;
  cluster?: Maybe<Cluster>;
  clusters: Array<Cluster>;
  deployment?: Maybe<Deployment>;
  deploymentServices: Array<DeployedService>;
  environment?: Maybe<Environment>;
  environmentServices: Array<DeployedService>;
  environments: Array<Environment>;
  /** Health check probe */
  ok: Scalars['Boolean']['output'];
  restore?: Maybe<Restore>;
  restores: Array<Restore>;
  task?: Maybe<Task>;
  tasks: Array<Task>;
};


export type QueryApplicationDriverArgs = {
  applicationDriverId: Scalars['UUID']['input'];
};


export type QueryBackupArgs = {
  backupId: Scalars['UUID']['input'];
};


export type QueryBackupScheduleArgs = {
  scheduleId: Scalars['UUID']['input'];
};


export type QueryBackupSchedulesArgs = {
  deploymentId: Scalars['UUID']['input'];
};


export type QueryBackupStorageLocationArgs = {
  backupStorageLocationId: Scalars['UUID']['input'];
};


export type QueryBackupsArgs = {
  instanceId: Scalars['UUID']['input'];
  status?: InputMaybe<Scalars['String']['input']>;
};


export type QueryClusterArgs = {
  clusterId: Scalars['UUID']['input'];
};


export type QueryDeploymentArgs = {
  deploymentId: Scalars['UUID']['input'];
};


export type QueryDeploymentServicesArgs = {
  deploymentId: Scalars['UUID']['input'];
};


export type QueryEnvironmentArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type QueryEnvironmentServicesArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type QueryRestoreArgs = {
  restoreId: Scalars['UUID']['input'];
};


export type QueryRestoresArgs = {
  backupId: Scalars['UUID']['input'];
  status?: InputMaybe<Scalars['String']['input']>;
};


export type QueryTaskArgs = {
  taskId: Scalars['UUID']['input'];
};

export type Restore = {
  __typename?: 'Restore';
  backupId: Scalars['UUID']['output'];
  completedAt?: Maybe<Scalars['DateTime']['output']>;
  componentStatuses?: Maybe<Array<ComponentRestoreStatus>>;
  createdOn: Scalars['DateTime']['output'];
  errorMessage?: Maybe<Scalars['String']['output']>;
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  startedAt?: Maybe<Scalars['DateTime']['output']>;
  status: Scalars['String']['output'];
  targetInstanceId?: Maybe<Scalars['UUID']['output']>;
  targetNamespace: Scalars['String']['output'];
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

export type ServiceDefinition = {
  __typename?: 'ServiceDefinition';
  component: Scalars['String']['output'];
  kind: Scalars['String']['output'];
  name: Scalars['String']['output'];
  port: Scalars['Int']['output'];
  scope: Scalars['String']['output'];
};

export type ServiceNameOverride = {
  driverServiceName: Scalars['String']['input'];
  overrideName: Scalars['String']['input'];
};

export type Task = {
  __typename?: 'Task';
  deploymentId?: Maybe<Scalars['UUID']['output']>;
  id: Scalars['UUID']['output'];
  message?: Maybe<Scalars['String']['output']>;
  status: Scalars['String']['output'];
  type: Scalars['String']['output'];
};

export type UpdateBackupStorageLocationResult = BackupStorageLocation | BackupStorageLocationNotFound;

export type AssignBackupStorageLocationMutationVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
  backupStorageLocationId: Scalars['UUID']['input'];
}>;


export type AssignBackupStorageLocationMutation = { __typename?: 'Mutation', assignBackupStorageLocation?: { __typename?: 'Environment', id: string, name: string, backupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string } | null } | null };

export type CreateBackupMutationVariables = Exact<{
  instanceId: Scalars['UUID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
}>;


export type CreateBackupMutation = { __typename?: 'Mutation', createBackup?: { __typename?: 'Backup', id: string, name: string, status: string, createdOn: any } | null };

export type CreateBackupStorageLocationMutationVariables = Exact<{
  name: Scalars['String']['input'];
  endpoint: Scalars['String']['input'];
  bucket: Scalars['String']['input'];
  region: Scalars['String']['input'];
  accessKeyId: Scalars['String']['input'];
  secretAccessKey: Scalars['String']['input'];
}>;


export type CreateBackupStorageLocationMutation = { __typename?: 'Mutation', createBackupStorageLocation:
    | { __typename?: 'BackupStorageLocation', id: string, name: string, endpoint: string, bucket: string, region: string, createdOn: any, updatedOn?: any | null, environmentCount: number }
    | { __typename?: 'BackupStorageLocationAlreadyExists', message: string, existingId: string }
   };

export type CreateClusterMutationVariables = Exact<{
  name: Scalars['String']['input'];
  config?: InputMaybe<Scalars['JSON']['input']>;
}>;


export type CreateClusterMutation = { __typename?: 'Mutation', createCluster?: { __typename?: 'Cluster', id: string, name: string, config: Record<string, unknown> } | null };

export type CreateEnvironmentMutationVariables = Exact<{
  name: Scalars['String']['input'];
  clusterId: Scalars['UUID']['input'];
  config?: InputMaybe<Scalars['JSON']['input']>;
}>;


export type CreateEnvironmentMutation = { __typename?: 'Mutation', createEnvironment?: { __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string } } | null };

export type CreateRestoreMutationVariables = Exact<{
  backupId: Scalars['UUID']['input'];
  targetNamespace: Scalars['String']['input'];
  targetInstanceId?: InputMaybe<Scalars['UUID']['input']>;
}>;


export type CreateRestoreMutation = { __typename?: 'Mutation', createRestore?: { __typename?: 'Restore', id: string, name: string, status: string, backupId: string, targetNamespace: string, targetInstanceId?: string | null, errorMessage?: string | null, createdOn: any } | null };

export type DeleteBackupMutationVariables = Exact<{
  backupId: Scalars['UUID']['input'];
}>;


export type DeleteBackupMutation = { __typename?: 'Mutation', deleteBackup?: string | null };

export type DeleteBackupStorageLocationMutationVariables = Exact<{
  backupStorageLocationId: Scalars['UUID']['input'];
}>;


export type DeleteBackupStorageLocationMutation = { __typename?: 'Mutation', deleteBackupStorageLocation:
    | { __typename?: 'BackupStorageLocationInUse', message: string, environmentNames: Array<string> }
    | { __typename?: 'DeleteSuccess', success: boolean }
   };

export type DeployMutationVariables = Exact<{
  version?: InputMaybe<Scalars['String']['input']>;
  driver: Scalars['String']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  environmentId: Scalars['UUID']['input'];
  config?: InputMaybe<Scalars['JSON']['input']>;
  parameters?: InputMaybe<Scalars['JSON']['input']>;
}>;


export type DeployMutation = { __typename?: 'Mutation', deploy?: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, deploymentId?: string | null } | null };

export type GetBackupStorageLocationQueryVariables = Exact<{
  backupStorageLocationId: Scalars['UUID']['input'];
}>;


export type GetBackupStorageLocationQuery = { __typename?: 'Query', backupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string, endpoint: string, bucket: string, region: string, createdOn: any, updatedOn?: any | null, environmentCount: number } | null };

export type GetClusterQueryVariables = Exact<{
  clusterId: Scalars['UUID']['input'];
}>;


export type GetClusterQuery = { __typename?: 'Query', cluster?: { __typename?: 'Cluster', id: string, name: string, config: Record<string, unknown>, createdOn: any, updatedOn?: any | null, environments: Array<{ __typename?: 'Environment', id: string, name: string }> } | null };

export type GetDeploymentQueryVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
}>;


export type GetDeploymentQuery = { __typename?: 'Query', deployment?: { __typename?: 'Deployment', id: string, name: string, status: string, config: Record<string, unknown>, parameters: Record<string, unknown>, applicationVersion: string, applicationDriverVersionId: string, environmentId: string, applicationInstance?: { __typename?: 'ApplicationInstance', id: string, name: string, status: string, applicationVersion: string, applicationDriverVersionId: string, deploymentId: string } | null, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }> } | null };

export type GetDriverQueryVariables = Exact<{
  applicationDriverId: Scalars['UUID']['input'];
}>;


export type GetDriverQuery = { __typename?: 'Query', applicationDriver?: { __typename?: 'ApplicationDriver', id: string, name: string, versions: Array<{ __typename?: 'ApplicationDriverVersion', id: string, version: string, supportedVersions: string, sourceType: string, sourceRepository: string, sourceBranch?: string | null, sourcePath?: string | null, components?: Record<string, unknown> | null, parameters: Array<{ __typename?: 'ParameterDefinition', name: string, label: string, kind: string, default?: Record<string, unknown> | null, values?: Array<string> | null }>, componentConfigs: Array<{ __typename?: 'ComponentConfig', id: string, name: string, config?: Record<string, unknown> | null }>, helmChart: { __typename?: 'HelmChart', id: string, name: string, version: string, repository: string, valueTemplate: string }, actions: Array<{ __typename?: 'Action', id: string, name: string, description: string, location: string }> }> } | null };

export type GetEnvironmentQueryVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
}>;


export type GetEnvironmentQuery = { __typename?: 'Query', environment?: { __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string }, backupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string } | null, deployments: Array<{ __typename?: 'Deployment', id: string, name: string, status: string, applicationVersion: string, applicationDriverVersionId: string, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }>, applicationInstance?: { __typename?: 'ApplicationInstance', id: string, status: string } | null }> } | null };

export type GetRestoreQueryVariables = Exact<{
  restoreId: Scalars['UUID']['input'];
}>;


export type GetRestoreQuery = { __typename?: 'Query', restore?: { __typename?: 'Restore', id: string, name: string, status: string, createdOn: any, startedAt?: any | null, completedAt?: any | null, targetNamespace: string, errorMessage?: string | null, backupId: string, targetInstanceId?: string | null, componentStatuses?: Array<{ __typename?: 'ComponentRestoreStatus', componentName: string, status: string, errorMessage?: string | null }> | null } | null };

export type GetTaskQueryVariables = Exact<{
  taskId: Scalars['UUID']['input'];
}>;


export type GetTaskQuery = { __typename?: 'Query', task?: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, deploymentId?: string | null } | null };

export type ListApplicationDriversQueryVariables = Exact<{ [key: string]: never; }>;


export type ListApplicationDriversQuery = { __typename?: 'Query', applicationDrivers: Array<{ __typename?: 'ApplicationDriver', id: string, name: string, versions: Array<{ __typename?: 'ApplicationDriverVersion', id: string, version: string, supportedVersions: string, defaultVersion?: string | null, parameters: Array<{ __typename?: 'ParameterDefinition', name: string, label: string, kind: string, default?: Record<string, unknown> | null, values?: Array<string> | null }> }> }> };

export type ListBackupStorageLocationsQueryVariables = Exact<{ [key: string]: never; }>;


export type ListBackupStorageLocationsQuery = { __typename?: 'Query', backupStorageLocations: Array<{ __typename?: 'BackupStorageLocation', id: string, name: string, endpoint: string, bucket: string, region: string, createdOn: any, updatedOn?: any | null, environmentCount: number }> };

export type ListBackupsQueryVariables = Exact<{
  instanceId: Scalars['UUID']['input'];
}>;


export type ListBackupsQuery = { __typename?: 'Query', backups: Array<{ __typename?: 'Backup', id: string, name: string, status: string, createdOn: any, completedAt?: any | null, sizeBytes?: number | null, errorMessage?: string | null }> };

export type ListClustersQueryVariables = Exact<{ [key: string]: never; }>;


export type ListClustersQuery = { __typename?: 'Query', clusters: Array<{ __typename?: 'Cluster', id: string, name: string, config: Record<string, unknown> }> };

export type ListDriversQueryVariables = Exact<{ [key: string]: never; }>;


export type ListDriversQuery = { __typename?: 'Query', applicationDrivers: Array<{ __typename?: 'ApplicationDriver', id: string, name: string, versions: Array<{ __typename?: 'ApplicationDriverVersion', id: string, version: string, sourceType: string, sourceRepository: string, sourceBranch?: string | null, sourcePath?: string | null }> }> };

export type ListEnvironmentsQueryVariables = Exact<{ [key: string]: never; }>;


export type ListEnvironmentsQuery = { __typename?: 'Query', environments: Array<{ __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string }, deployments: Array<{ __typename?: 'Deployment', id: string, name: string, status: string, applicationVersion: string, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }> }> }> };

export type ListRestoresQueryVariables = Exact<{
  backupId: Scalars['UUID']['input'];
  status?: InputMaybe<Scalars['String']['input']>;
}>;


export type ListRestoresQuery = { __typename?: 'Query', restores: Array<{ __typename?: 'Restore', id: string, name: string, status: string, createdOn: any, startedAt?: any | null, completedAt?: any | null, targetNamespace: string, errorMessage?: string | null, componentStatuses?: Array<{ __typename?: 'ComponentRestoreStatus', componentName: string, status: string, errorMessage?: string | null }> | null }> };

export type LoadLocalDriverMutationVariables = Exact<{
  path: Scalars['String']['input'];
}>;


export type LoadLocalDriverMutation = { __typename?: 'Mutation', loadLocalApplicationDriverVersion?: { __typename?: 'ApplicationDriverVersion', id: string, version: string, applicationDriverId: string } | null };

export type LoadRemoteDriverMutationVariables = Exact<{
  repositoryUrl: Scalars['String']['input'];
  branch: Scalars['String']['input'];
}>;


export type LoadRemoteDriverMutation = { __typename?: 'Mutation', loadRemoteApplicationDriverVersion?: { __typename?: 'ApplicationDriverVersion', id: string, version: string, applicationDriverId: string } | null };

export type UnassignBackupStorageLocationMutationVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
}>;


export type UnassignBackupStorageLocationMutation = { __typename?: 'Mutation', unassignBackupStorageLocation?: { __typename?: 'Environment', id: string, name: string, backupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string } | null } | null };

export type UpdateBackupStorageLocationMutationVariables = Exact<{
  backupStorageLocationId: Scalars['UUID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  endpoint?: InputMaybe<Scalars['String']['input']>;
  bucket?: InputMaybe<Scalars['String']['input']>;
  region?: InputMaybe<Scalars['String']['input']>;
  accessKeyId?: InputMaybe<Scalars['String']['input']>;
  secretAccessKey?: InputMaybe<Scalars['String']['input']>;
}>;


export type UpdateBackupStorageLocationMutation = { __typename?: 'Mutation', updateBackupStorageLocation:
    | { __typename?: 'BackupStorageLocation', id: string, name: string, endpoint: string, bucket: string, region: string, createdOn: any, updatedOn?: any | null, environmentCount: number }
    | { __typename?: 'BackupStorageLocationNotFound', message: string, backupStorageLocationId: string }
   };

export type UpdateDeploymentVersionMutationVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
  version: Scalars['String']['input'];
  parameters?: InputMaybe<Scalars['JSON']['input']>;
}>;


export type UpdateDeploymentVersionMutation = { __typename?: 'Mutation', updateDeploymentVersion?: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, deploymentId?: string | null } | null };


export const AssignBackupStorageLocationDocument = gql`
    mutation AssignBackupStorageLocation($environmentId: UUID!, $backupStorageLocationId: UUID!) {
  assignBackupStorageLocation(
    environmentId: $environmentId
    backupStorageLocationId: $backupStorageLocationId
  ) {
    id
    name
    backupStorageLocation {
      id
      name
    }
  }
}
    `;

export function useAssignBackupStorageLocationMutation() {
  return Urql.useMutation<AssignBackupStorageLocationMutation, AssignBackupStorageLocationMutationVariables>(AssignBackupStorageLocationDocument);
};
export const CreateBackupDocument = gql`
    mutation CreateBackup($instanceId: UUID!, $name: String) {
  createBackup(instanceId: $instanceId, name: $name) {
    id
    name
    status
    createdOn
  }
}
    `;

export function useCreateBackupMutation() {
  return Urql.useMutation<CreateBackupMutation, CreateBackupMutationVariables>(CreateBackupDocument);
};
export const CreateBackupStorageLocationDocument = gql`
    mutation CreateBackupStorageLocation($name: String!, $endpoint: String!, $bucket: String!, $region: String!, $accessKeyId: String!, $secretAccessKey: String!) {
  createBackupStorageLocation(
    name: $name
    endpoint: $endpoint
    bucket: $bucket
    region: $region
    accessKeyId: $accessKeyId
    secretAccessKey: $secretAccessKey
  ) {
    ... on BackupStorageLocation {
      id
      name
      endpoint
      bucket
      region
      createdOn
      updatedOn
      environmentCount
    }
    ... on BackupStorageLocationAlreadyExists {
      message
      existingId
    }
  }
}
    `;

export function useCreateBackupStorageLocationMutation() {
  return Urql.useMutation<CreateBackupStorageLocationMutation, CreateBackupStorageLocationMutationVariables>(CreateBackupStorageLocationDocument);
};
export const CreateClusterDocument = gql`
    mutation CreateCluster($name: String!, $config: JSON) {
  createCluster(name: $name, config: $config) {
    id
    name
    config
  }
}
    `;

export function useCreateClusterMutation() {
  return Urql.useMutation<CreateClusterMutation, CreateClusterMutationVariables>(CreateClusterDocument);
};
export const CreateEnvironmentDocument = gql`
    mutation CreateEnvironment($name: String!, $clusterId: UUID!, $config: JSON) {
  createEnvironment(name: $name, clusterId: $clusterId, config: $config) {
    id
    name
    config
    cluster {
      id
      name
    }
  }
}
    `;

export function useCreateEnvironmentMutation() {
  return Urql.useMutation<CreateEnvironmentMutation, CreateEnvironmentMutationVariables>(CreateEnvironmentDocument);
};
export const CreateRestoreDocument = gql`
    mutation CreateRestore($backupId: UUID!, $targetNamespace: String!, $targetInstanceId: UUID) {
  createRestore(
    backupId: $backupId
    targetNamespace: $targetNamespace
    targetInstanceId: $targetInstanceId
  ) {
    id
    name
    status
    backupId
    targetNamespace
    targetInstanceId
    errorMessage
    createdOn
  }
}
    `;

export function useCreateRestoreMutation() {
  return Urql.useMutation<CreateRestoreMutation, CreateRestoreMutationVariables>(CreateRestoreDocument);
};
export const DeleteBackupDocument = gql`
    mutation DeleteBackup($backupId: UUID!) {
  deleteBackup(backupId: $backupId)
}
    `;

export function useDeleteBackupMutation() {
  return Urql.useMutation<DeleteBackupMutation, DeleteBackupMutationVariables>(DeleteBackupDocument);
};
export const DeleteBackupStorageLocationDocument = gql`
    mutation DeleteBackupStorageLocation($backupStorageLocationId: UUID!) {
  deleteBackupStorageLocation(backupStorageLocationId: $backupStorageLocationId) {
    ... on DeleteSuccess {
      success
    }
    ... on BackupStorageLocationInUse {
      message
      environmentNames
    }
  }
}
    `;

export function useDeleteBackupStorageLocationMutation() {
  return Urql.useMutation<DeleteBackupStorageLocationMutation, DeleteBackupStorageLocationMutationVariables>(DeleteBackupStorageLocationDocument);
};
export const DeployDocument = gql`
    mutation Deploy($version: String, $driver: String!, $name: String, $environmentId: UUID!, $config: JSON, $parameters: JSON) {
  deploy(
    version: $version
    driver: $driver
    name: $name
    environmentId: $environmentId
    config: $config
    parameters: $parameters
  ) {
    id
    type
    status
    message
    deploymentId
  }
}
    `;

export function useDeployMutation() {
  return Urql.useMutation<DeployMutation, DeployMutationVariables>(DeployDocument);
};
export const GetBackupStorageLocationDocument = gql`
    query GetBackupStorageLocation($backupStorageLocationId: UUID!) {
  backupStorageLocation(backupStorageLocationId: $backupStorageLocationId) {
    id
    name
    endpoint
    bucket
    region
    createdOn
    updatedOn
    environmentCount
  }
}
    `;

export function useGetBackupStorageLocationQuery(options: Omit<Urql.UseQueryArgs<GetBackupStorageLocationQueryVariables>, 'query'>) {
  return Urql.useQuery<GetBackupStorageLocationQuery, GetBackupStorageLocationQueryVariables>({ query: GetBackupStorageLocationDocument, ...options });
};
export const GetClusterDocument = gql`
    query GetCluster($clusterId: UUID!) {
  cluster(clusterId: $clusterId) {
    id
    name
    config
    createdOn
    updatedOn
    environments {
      id
      name
    }
  }
}
    `;

export function useGetClusterQuery(options: Omit<Urql.UseQueryArgs<GetClusterQueryVariables>, 'query'>) {
  return Urql.useQuery<GetClusterQuery, GetClusterQueryVariables>({ query: GetClusterDocument, ...options });
};
export const GetDeploymentDocument = gql`
    query GetDeployment($deploymentId: UUID!) {
  deployment(deploymentId: $deploymentId) {
    id
    name
    status
    config
    parameters
    applicationVersion
    applicationDriverVersionId
    environmentId
    applicationInstance {
      id
      name
      status
      applicationVersion
      applicationDriverVersionId
      deploymentId
    }
    components {
      id
      name
      enabled
    }
  }
}
    `;

export function useGetDeploymentQuery(options: Omit<Urql.UseQueryArgs<GetDeploymentQueryVariables>, 'query'>) {
  return Urql.useQuery<GetDeploymentQuery, GetDeploymentQueryVariables>({ query: GetDeploymentDocument, ...options });
};
export const GetDriverDocument = gql`
    query GetDriver($applicationDriverId: UUID!) {
  applicationDriver(applicationDriverId: $applicationDriverId) {
    id
    name
    versions {
      id
      version
      supportedVersions
      sourceType
      sourceRepository
      sourceBranch
      sourcePath
      components
      parameters {
        name
        label
        kind
        default
        values
      }
      componentConfigs {
        id
        name
        config
      }
      helmChart {
        id
        name
        version
        repository
        valueTemplate
      }
      actions {
        id
        name
        description
        location
      }
    }
  }
}
    `;

export function useGetDriverQuery(options: Omit<Urql.UseQueryArgs<GetDriverQueryVariables>, 'query'>) {
  return Urql.useQuery<GetDriverQuery, GetDriverQueryVariables>({ query: GetDriverDocument, ...options });
};
export const GetEnvironmentDocument = gql`
    query GetEnvironment($environmentId: UUID!) {
  environment(environmentId: $environmentId) {
    id
    name
    config
    cluster {
      id
      name
    }
    backupStorageLocation {
      id
      name
    }
    deployments {
      id
      name
      status
      applicationVersion
      applicationDriverVersionId
      components {
        id
        name
        enabled
      }
      applicationInstance {
        id
        status
      }
    }
  }
}
    `;

export function useGetEnvironmentQuery(options: Omit<Urql.UseQueryArgs<GetEnvironmentQueryVariables>, 'query'>) {
  return Urql.useQuery<GetEnvironmentQuery, GetEnvironmentQueryVariables>({ query: GetEnvironmentDocument, ...options });
};
export const GetRestoreDocument = gql`
    query GetRestore($restoreId: UUID!) {
  restore(restoreId: $restoreId) {
    id
    name
    status
    createdOn
    startedAt
    completedAt
    targetNamespace
    errorMessage
    backupId
    targetInstanceId
    componentStatuses {
      componentName
      status
      errorMessage
    }
  }
}
    `;

export function useGetRestoreQuery(options: Omit<Urql.UseQueryArgs<GetRestoreQueryVariables>, 'query'>) {
  return Urql.useQuery<GetRestoreQuery, GetRestoreQueryVariables>({ query: GetRestoreDocument, ...options });
};
export const GetTaskDocument = gql`
    query GetTask($taskId: UUID!) {
  task(taskId: $taskId) {
    id
    type
    status
    message
    deploymentId
  }
}
    `;

export function useGetTaskQuery(options: Omit<Urql.UseQueryArgs<GetTaskQueryVariables>, 'query'>) {
  return Urql.useQuery<GetTaskQuery, GetTaskQueryVariables>({ query: GetTaskDocument, ...options });
};
export const ListApplicationDriversDocument = gql`
    query ListApplicationDrivers {
  applicationDrivers {
    id
    name
    versions {
      id
      version
      supportedVersions
      defaultVersion
      parameters {
        name
        label
        kind
        default
        values
      }
    }
  }
}
    `;

export function useListApplicationDriversQuery(options?: Omit<Urql.UseQueryArgs<ListApplicationDriversQueryVariables>, 'query'>) {
  return Urql.useQuery<ListApplicationDriversQuery, ListApplicationDriversQueryVariables>({ query: ListApplicationDriversDocument, ...options });
};
export const ListBackupStorageLocationsDocument = gql`
    query ListBackupStorageLocations {
  backupStorageLocations {
    id
    name
    endpoint
    bucket
    region
    createdOn
    updatedOn
    environmentCount
  }
}
    `;

export function useListBackupStorageLocationsQuery(options?: Omit<Urql.UseQueryArgs<ListBackupStorageLocationsQueryVariables>, 'query'>) {
  return Urql.useQuery<ListBackupStorageLocationsQuery, ListBackupStorageLocationsQueryVariables>({ query: ListBackupStorageLocationsDocument, ...options });
};
export const ListBackupsDocument = gql`
    query ListBackups($instanceId: UUID!) {
  backups(instanceId: $instanceId) {
    id
    name
    status
    createdOn
    completedAt
    sizeBytes
    errorMessage
  }
}
    `;

export function useListBackupsQuery(options: Omit<Urql.UseQueryArgs<ListBackupsQueryVariables>, 'query'>) {
  return Urql.useQuery<ListBackupsQuery, ListBackupsQueryVariables>({ query: ListBackupsDocument, ...options });
};
export const ListClustersDocument = gql`
    query ListClusters {
  clusters {
    id
    name
    config
  }
}
    `;

export function useListClustersQuery(options?: Omit<Urql.UseQueryArgs<ListClustersQueryVariables>, 'query'>) {
  return Urql.useQuery<ListClustersQuery, ListClustersQueryVariables>({ query: ListClustersDocument, ...options });
};
export const ListDriversDocument = gql`
    query ListDrivers {
  applicationDrivers {
    id
    name
    versions {
      id
      version
      sourceType
      sourceRepository
      sourceBranch
      sourcePath
    }
  }
}
    `;

export function useListDriversQuery(options?: Omit<Urql.UseQueryArgs<ListDriversQueryVariables>, 'query'>) {
  return Urql.useQuery<ListDriversQuery, ListDriversQueryVariables>({ query: ListDriversDocument, ...options });
};
export const ListEnvironmentsDocument = gql`
    query ListEnvironments {
  environments {
    id
    name
    config
    cluster {
      id
      name
    }
    deployments {
      id
      name
      status
      applicationVersion
      components {
        id
        name
        enabled
      }
    }
  }
}
    `;

export function useListEnvironmentsQuery(options?: Omit<Urql.UseQueryArgs<ListEnvironmentsQueryVariables>, 'query'>) {
  return Urql.useQuery<ListEnvironmentsQuery, ListEnvironmentsQueryVariables>({ query: ListEnvironmentsDocument, ...options });
};
export const ListRestoresDocument = gql`
    query ListRestores($backupId: UUID!, $status: String) {
  restores(backupId: $backupId, status: $status) {
    id
    name
    status
    createdOn
    startedAt
    completedAt
    targetNamespace
    errorMessage
    componentStatuses {
      componentName
      status
      errorMessage
    }
  }
}
    `;

export function useListRestoresQuery(options: Omit<Urql.UseQueryArgs<ListRestoresQueryVariables>, 'query'>) {
  return Urql.useQuery<ListRestoresQuery, ListRestoresQueryVariables>({ query: ListRestoresDocument, ...options });
};
export const LoadLocalDriverDocument = gql`
    mutation LoadLocalDriver($path: String!) {
  loadLocalApplicationDriverVersion(path: $path) {
    id
    version
    applicationDriverId
  }
}
    `;

export function useLoadLocalDriverMutation() {
  return Urql.useMutation<LoadLocalDriverMutation, LoadLocalDriverMutationVariables>(LoadLocalDriverDocument);
};
export const LoadRemoteDriverDocument = gql`
    mutation LoadRemoteDriver($repositoryUrl: String!, $branch: String!) {
  loadRemoteApplicationDriverVersion(
    repositoryUrl: $repositoryUrl
    branch: $branch
  ) {
    id
    version
    applicationDriverId
  }
}
    `;

export function useLoadRemoteDriverMutation() {
  return Urql.useMutation<LoadRemoteDriverMutation, LoadRemoteDriverMutationVariables>(LoadRemoteDriverDocument);
};
export const UnassignBackupStorageLocationDocument = gql`
    mutation UnassignBackupStorageLocation($environmentId: UUID!) {
  unassignBackupStorageLocation(environmentId: $environmentId) {
    id
    name
    backupStorageLocation {
      id
      name
    }
  }
}
    `;

export function useUnassignBackupStorageLocationMutation() {
  return Urql.useMutation<UnassignBackupStorageLocationMutation, UnassignBackupStorageLocationMutationVariables>(UnassignBackupStorageLocationDocument);
};
export const UpdateBackupStorageLocationDocument = gql`
    mutation UpdateBackupStorageLocation($backupStorageLocationId: UUID!, $name: String, $endpoint: String, $bucket: String, $region: String, $accessKeyId: String, $secretAccessKey: String) {
  updateBackupStorageLocation(
    backupStorageLocationId: $backupStorageLocationId
    name: $name
    endpoint: $endpoint
    bucket: $bucket
    region: $region
    accessKeyId: $accessKeyId
    secretAccessKey: $secretAccessKey
  ) {
    ... on BackupStorageLocation {
      id
      name
      endpoint
      bucket
      region
      createdOn
      updatedOn
      environmentCount
    }
    ... on BackupStorageLocationNotFound {
      message
      backupStorageLocationId
    }
  }
}
    `;

export function useUpdateBackupStorageLocationMutation() {
  return Urql.useMutation<UpdateBackupStorageLocationMutation, UpdateBackupStorageLocationMutationVariables>(UpdateBackupStorageLocationDocument);
};
export const UpdateDeploymentVersionDocument = gql`
    mutation UpdateDeploymentVersion($deploymentId: UUID!, $version: String!, $parameters: JSON) {
  updateDeploymentVersion(
    deploymentId: $deploymentId
    version: $version
    parameters: $parameters
  ) {
    id
    type
    status
    message
    deploymentId
  }
}
    `;

export function useUpdateDeploymentVersionMutation() {
  return Urql.useMutation<UpdateDeploymentVersionMutation, UpdateDeploymentVersionMutationVariables>(UpdateDeploymentVersionDocument);
};