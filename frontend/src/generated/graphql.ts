import { useMutation, useQuery, type UseMutationOptions, type UseQueryOptions } from '@tanstack/react-query';
import { graphqlFetcher } from '../lib/graphql-fetcher';
export type Maybe<T> = T | null;
export type InputMaybe<T> = Maybe<T>;
export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };
export type MakeOptional<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]?: Maybe<T[SubKey]> };
export type MakeMaybe<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]: Maybe<T[SubKey]> };
export type MakeEmpty<T extends { [key: string]: unknown }, K extends keyof T> = { [_ in K]?: never };
export type Incremental<T> = T | { [P in keyof T]?: P extends ' $fragmentName' | '__typename' ? T[P] : never };
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string; }
  String: { input: string; output: string; }
  Boolean: { input: boolean; output: boolean; }
  Int: { input: number; output: number; }
  Float: { input: number; output: number; }
  /** Date with time (isoformat) */
  DateTime: { input: any; output: any; }
  /** The `JSON` scalar type represents JSON values as specified by [ECMA-404](https://ecma-international.org/wp-content/uploads/ECMA-404_2nd_edition_december_2017.pdf). */
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
  applicationDriver: ApplicationDriver;
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
  applicationDriverVersion: ApplicationDriverVersion;
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
  instance: ApplicationInstance;
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
  deployment: Deployment;
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

export type BackupStatus =
  | 'COMPLETED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'PENDING';

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

export type CallbackResponse = {
  __typename?: 'CallbackResponse';
  message: Scalars['String']['output'];
  success: Scalars['Boolean']['output'];
};

export type Cluster = {
  __typename?: 'Cluster';
  capabilities: Scalars['JSON']['output'];
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

export type ContextChange = {
  __typename?: 'ContextChange';
  action: Scalars['String']['output'];
  newValue?: Maybe<Scalars['JSON']['output']>;
  oldValue?: Maybe<Scalars['JSON']['output']>;
  path: Scalars['String']['output'];
};

export type ContextDiff = {
  __typename?: 'ContextDiff';
  changes: Array<ContextChange>;
};

export type CrdConditionInput = {
  lastTransitionTime?: InputMaybe<Scalars['DateTime']['input']>;
  message?: InputMaybe<Scalars['String']['input']>;
  reason?: InputMaybe<Scalars['String']['input']>;
  status: Scalars['String']['input'];
  type: Scalars['String']['input'];
};

export type CrdConditionType = {
  __typename?: 'CrdConditionType';
  lastTransitionTime?: Maybe<Scalars['DateTime']['output']>;
  message?: Maybe<Scalars['String']['output']>;
  reason?: Maybe<Scalars['String']['output']>;
  status: Scalars['String']['output'];
  type: Scalars['String']['output'];
};

export type DeployedService = {
  __typename?: 'DeployedService';
  component: Scalars['String']['output'];
  deploymentId: Scalars['UUID']['output'];
  driverServiceName: Scalars['String']['output'];
  humanReadableFqdn?: Maybe<Scalars['String']['output']>;
  id: Scalars['UUID']['output'];
  kind: Scalars['String']['output'];
  port: Scalars['Int']['output'];
  primaryFqdn?: Maybe<Scalars['String']['output']>;
  resolvedName: Scalars['String']['output'];
  scope: Scalars['String']['output'];
};

export type Deployment = {
  __typename?: 'Deployment';
  applicationDriverVersion: ApplicationDriverVersion;
  applicationDriverVersionId: Scalars['UUID']['output'];
  applicationInstance?: Maybe<ApplicationInstance>;
  applicationVersion: Scalars['String']['output'];
  components: Array<Component>;
  config: Scalars['JSON']['output'];
  crdStatus?: Maybe<DeploymentStatusType>;
  deployedServices: Array<DeployedService>;
  environment: Environment;
  environmentId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  internal: Scalars['Boolean']['output'];
  name: Scalars['String']['output'];
  parameters: Scalars['JSON']['output'];
  podStatuses: Array<PodStatus>;
  status: Scalars['String']['output'];
};

export type DeploymentPodStatusReport = {
  deploymentId: Scalars['UUID']['input'];
  pods: Array<PodStatusInput>;
};

export type DeploymentStatusReportInput = {
  conditions?: InputMaybe<Array<CrdConditionInput>>;
  deploymentId: Scalars['UUID']['input'];
  displayState?: InputMaybe<Scalars['String']['input']>;
  instanceId?: InputMaybe<Scalars['UUID']['input']>;
  managedResourceCounts?: InputMaybe<ManagedResourceCountsInput>;
  message?: InputMaybe<Scalars['String']['input']>;
  phase: Scalars['String']['input'];
};

export type DeploymentStatusType = {
  __typename?: 'DeploymentStatusType';
  conditions: Array<CrdConditionType>;
  createdOn?: Maybe<Scalars['DateTime']['output']>;
  deploymentId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  lastPolledAt?: Maybe<Scalars['DateTime']['output']>;
  managedResourceCounts?: Maybe<ManagedResourceCountsType>;
  message?: Maybe<Scalars['String']['output']>;
  phase: Scalars['String']['output'];
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

export type DeploymentTimelineEntry = {
  __typename?: 'DeploymentTimelineEntry';
  applicationVersion?: Maybe<Scalars['String']['output']>;
  contextDiff?: Maybe<ContextDiff>;
  task: Task;
};

export type Environment = {
  __typename?: 'Environment';
  backupStorageLocation?: Maybe<BackupStorageLocation>;
  capabilities: Scalars['JSON']['output'];
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

export type ManagedResourceCountsInput = {
  helmReleases?: Scalars['Int']['input'];
  middlewares?: Scalars['Int']['input'];
  networkPolicies?: Scalars['Int']['input'];
  secrets?: Scalars['Int']['input'];
  services?: Scalars['Int']['input'];
};

export type ManagedResourceCountsType = {
  __typename?: 'ManagedResourceCountsType';
  helmReleases: Scalars['Int']['output'];
  middlewares: Scalars['Int']['output'];
  networkPolicies: Scalars['Int']['output'];
  secrets: Scalars['Int']['output'];
  services: Scalars['Int']['output'];
};

export type Mutation = {
  __typename?: 'Mutation';
  assignBackupStorageLocation?: Maybe<Environment>;
  callback: CallbackResponse;
  createBackup?: Maybe<Backup>;
  createBackupSchedule?: Maybe<BackupSchedule>;
  createBackupStorageLocation?: Maybe<BackupStorageLocation>;
  createCluster?: Maybe<Cluster>;
  createEnvironment?: Maybe<Environment>;
  createRestore?: Maybe<Restore>;
  deleteBackup?: Maybe<Scalars['String']['output']>;
  deleteBackupSchedule?: Maybe<Scalars['String']['output']>;
  deleteBackupStorageLocation?: Maybe<Scalars['String']['output']>;
  deleteCluster?: Maybe<Scalars['String']['output']>;
  deleteEnvironment?: Maybe<Scalars['String']['output']>;
  deploy?: Maybe<Task>;
  loadLocalApplicationDriverVersion?: Maybe<ApplicationDriverVersion>;
  loadRemoteApplicationDriverVersion?: Maybe<ApplicationDriverVersion>;
  reportDeploymentStatuses: ReportDeploymentStatusesResponse;
  reportPodStatuses: ReportPodStatusesResponse;
  runJob?: Maybe<Task>;
  startComponents?: Maybe<Task>;
  stopComponents?: Maybe<Task>;
  unassignBackupStorageLocation?: Maybe<Environment>;
  updateBackupSchedule?: Maybe<BackupSchedule>;
  updateBackupStorageLocation?: Maybe<BackupStorageLocation>;
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
  name?: Scalars['String']['input'];
};


export type MutationCreateEnvironmentArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
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
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
};


export type MutationDeleteEnvironmentArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentName?: InputMaybe<Scalars['String']['input']>;
};


export type MutationDeployArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
  config?: InputMaybe<Scalars['JSON']['input']>;
  driver: Scalars['String']['input'];
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentName?: InputMaybe<Scalars['String']['input']>;
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


export type MutationReportDeploymentStatusesArgs = {
  reports: Array<DeploymentStatusReportInput>;
};


export type MutationReportPodStatusesArgs = {
  reports: Array<DeploymentPodStatusReport>;
};


export type MutationRunJobArgs = {
  commands: Array<Scalars['String']['input']>;
  deploymentId: Scalars['UUID']['input'];
  env: Array<Scalars['JSON']['input']>;
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

export type PodPhase =
  | 'FAILED'
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'UNKNOWN';

export type PodStatus = {
  __typename?: 'PodStatus';
  containerStatuses: Scalars['JSON']['output'];
  createdOn?: Maybe<Scalars['DateTime']['output']>;
  deploymentId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  lastPolledAt?: Maybe<Scalars['DateTime']['output']>;
  namespace: Scalars['String']['output'];
  nodeName?: Maybe<Scalars['String']['output']>;
  phase: PodPhase;
  podName: Scalars['String']['output'];
  ready: Scalars['Boolean']['output'];
  restartCount: Scalars['Int']['output'];
  startedAt?: Maybe<Scalars['DateTime']['output']>;
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

export type PodStatusInput = {
  containerStatuses?: InputMaybe<Scalars['JSON']['input']>;
  namespace: Scalars['String']['input'];
  nodeName?: InputMaybe<Scalars['String']['input']>;
  phase: PodPhase;
  podName: Scalars['String']['input'];
  ready: Scalars['Boolean']['input'];
  restartCount: Scalars['Int']['input'];
  startedAt?: InputMaybe<Scalars['DateTime']['input']>;
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
  deploymentTimeline: Array<DeploymentTimelineEntry>;
  environment?: Maybe<Environment>;
  environmentServices: Array<DeployedService>;
  environments: Array<Environment>;
  /** Health check probe */
  ok: Scalars['Boolean']['output'];
  podStatuses: Array<PodStatus>;
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
  status?: InputMaybe<BackupStatus>;
};


export type QueryClusterArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
};


export type QueryDeploymentArgs = {
  deploymentId: Scalars['UUID']['input'];
};


export type QueryDeploymentServicesArgs = {
  deploymentId: Scalars['UUID']['input'];
};


export type QueryDeploymentTimelineArgs = {
  deploymentId: Scalars['UUID']['input'];
};


export type QueryEnvironmentArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentName?: InputMaybe<Scalars['String']['input']>;
};


export type QueryEnvironmentServicesArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type QueryPodStatusesArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  deploymentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
};


export type QueryRestoreArgs = {
  restoreId: Scalars['UUID']['input'];
};


export type QueryRestoresArgs = {
  backupId: Scalars['UUID']['input'];
  status?: InputMaybe<RestoreStatus>;
};


export type QueryTaskArgs = {
  taskId: Scalars['UUID']['input'];
};

export type ReportDeploymentStatusesResponse = {
  __typename?: 'ReportDeploymentStatusesResponse';
  deploymentsUpdated: Scalars['Int']['output'];
  message: Scalars['String']['output'];
  statusesUpdated: Scalars['Int']['output'];
  success: Scalars['Boolean']['output'];
};

export type ReportPodStatusesResponse = {
  __typename?: 'ReportPodStatusesResponse';
  message: Scalars['String']['output'];
  podsRemoved: Scalars['Int']['output'];
  podsUpdated: Scalars['Int']['output'];
  success: Scalars['Boolean']['output'];
};

export type Restore = {
  __typename?: 'Restore';
  backup: Backup;
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

export type RestoreStatus =
  | 'COMPLETED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'PENDING';

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
  createdOn?: Maybe<Scalars['DateTime']['output']>;
  deployment?: Maybe<Deployment>;
  deploymentId?: Maybe<Scalars['UUID']['output']>;
  id: Scalars['UUID']['output'];
  message?: Maybe<Scalars['String']['output']>;
  status: Scalars['String']['output'];
  type: Scalars['String']['output'];
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

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


export type CreateBackupStorageLocationMutation = { __typename?: 'Mutation', createBackupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string, endpoint: string, bucket: string, region: string, createdOn: any, updatedOn?: any | null, environmentCount: number } | null };

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


export type DeleteBackupStorageLocationMutation = { __typename?: 'Mutation', deleteBackupStorageLocation?: string | null };

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


export type GetDeploymentQuery = { __typename?: 'Query', deployment?: { __typename?: 'Deployment', id: string, name: string, status: string, config: Record<string, unknown>, parameters: Record<string, unknown>, applicationVersion: string, applicationDriverVersionId: string, environmentId: string, applicationInstance?: { __typename?: 'ApplicationInstance', id: string, name: string, status: string, applicationVersion: string, applicationDriverVersionId: string, deploymentId: string } | null, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }>, deployedServices: Array<{ __typename?: 'DeployedService', id: string, driverServiceName: string, resolvedName: string, kind: string, port: number, primaryFqdn?: string | null, humanReadableFqdn?: string | null }> } | null };

export type GetDeploymentTimelineQueryVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
}>;


export type GetDeploymentTimelineQuery = { __typename?: 'Query', deploymentTimeline: Array<{ __typename?: 'DeploymentTimelineEntry', applicationVersion?: string | null, task: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, createdOn?: any | null, updatedOn?: any | null }, contextDiff?: { __typename?: 'ContextDiff', changes: Array<{ __typename?: 'ContextChange', path: string, action: string, oldValue?: Record<string, unknown> | null, newValue?: Record<string, unknown> | null }> } | null }> };

export type GetDriverQueryVariables = Exact<{
  applicationDriverId: Scalars['UUID']['input'];
}>;


export type GetDriverQuery = { __typename?: 'Query', applicationDriver?: { __typename?: 'ApplicationDriver', id: string, name: string, versions: Array<{ __typename?: 'ApplicationDriverVersion', id: string, version: string, supportedVersions: string, sourceType: string, sourceRepository: string, sourceBranch?: string | null, sourcePath?: string | null, components?: Record<string, unknown> | null, parameters: Array<{ __typename?: 'ParameterDefinition', name: string, label: string, kind: string, default?: Record<string, unknown> | null, values?: Array<string> | null }>, componentConfigs: Array<{ __typename?: 'ComponentConfig', id: string, name: string, config?: Record<string, unknown> | null }>, helmChart: { __typename?: 'HelmChart', id: string, name: string, version: string, repository: string, valueTemplate: string }, actions: Array<{ __typename?: 'Action', id: string, name: string, description: string, location: string }> }> } | null };

export type GetEnvironmentQueryVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
}>;


export type GetEnvironmentQuery = { __typename?: 'Query', environment?: { __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string }, backupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string } | null, deployments: Array<{ __typename?: 'Deployment', id: string, name: string, status: string, internal: boolean, applicationVersion: string, applicationDriverVersionId: string, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }>, applicationInstance?: { __typename?: 'ApplicationInstance', id: string, status: string } | null }> } | null };

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


export type ListEnvironmentsQuery = { __typename?: 'Query', environments: Array<{ __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string }, deployments: Array<{ __typename?: 'Deployment', id: string, name: string, status: string, internal: boolean, applicationVersion: string, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }> }> }> };

export type ListRestoresQueryVariables = Exact<{
  backupId: Scalars['UUID']['input'];
  status?: InputMaybe<RestoreStatus>;
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


export type UpdateBackupStorageLocationMutation = { __typename?: 'Mutation', updateBackupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string, endpoint: string, bucket: string, region: string, createdOn: any, updatedOn?: any | null, environmentCount: number } | null };

export type UpdateDeploymentVersionMutationVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
  version: Scalars['String']['input'];
  parameters?: InputMaybe<Scalars['JSON']['input']>;
}>;


export type UpdateDeploymentVersionMutation = { __typename?: 'Mutation', updateDeploymentVersion?: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, deploymentId?: string | null } | null };



export const AssignBackupStorageLocationDocument = `
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

export const useAssignBackupStorageLocationMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<AssignBackupStorageLocationMutation, TError, AssignBackupStorageLocationMutationVariables, TContext>) => {
    
    return useMutation<AssignBackupStorageLocationMutation, TError, AssignBackupStorageLocationMutationVariables, TContext>(
      {
    mutationKey: ['AssignBackupStorageLocation'],
    mutationFn: (variables?: AssignBackupStorageLocationMutationVariables) => graphqlFetcher<AssignBackupStorageLocationMutation, AssignBackupStorageLocationMutationVariables>(AssignBackupStorageLocationDocument, variables)(),
    ...options
  }
    )};

export const CreateBackupDocument = `
    mutation CreateBackup($instanceId: UUID!, $name: String) {
  createBackup(instanceId: $instanceId, name: $name) {
    id
    name
    status
    createdOn
  }
}
    `;

export const useCreateBackupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateBackupMutation, TError, CreateBackupMutationVariables, TContext>) => {
    
    return useMutation<CreateBackupMutation, TError, CreateBackupMutationVariables, TContext>(
      {
    mutationKey: ['CreateBackup'],
    mutationFn: (variables?: CreateBackupMutationVariables) => graphqlFetcher<CreateBackupMutation, CreateBackupMutationVariables>(CreateBackupDocument, variables)(),
    ...options
  }
    )};

export const CreateBackupStorageLocationDocument = `
    mutation CreateBackupStorageLocation($name: String!, $endpoint: String!, $bucket: String!, $region: String!, $accessKeyId: String!, $secretAccessKey: String!) {
  createBackupStorageLocation(
    name: $name
    endpoint: $endpoint
    bucket: $bucket
    region: $region
    accessKeyId: $accessKeyId
    secretAccessKey: $secretAccessKey
  ) {
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

export const useCreateBackupStorageLocationMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateBackupStorageLocationMutation, TError, CreateBackupStorageLocationMutationVariables, TContext>) => {
    
    return useMutation<CreateBackupStorageLocationMutation, TError, CreateBackupStorageLocationMutationVariables, TContext>(
      {
    mutationKey: ['CreateBackupStorageLocation'],
    mutationFn: (variables?: CreateBackupStorageLocationMutationVariables) => graphqlFetcher<CreateBackupStorageLocationMutation, CreateBackupStorageLocationMutationVariables>(CreateBackupStorageLocationDocument, variables)(),
    ...options
  }
    )};

export const CreateClusterDocument = `
    mutation CreateCluster($name: String!, $config: JSON) {
  createCluster(name: $name, config: $config) {
    id
    name
    config
  }
}
    `;

export const useCreateClusterMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateClusterMutation, TError, CreateClusterMutationVariables, TContext>) => {
    
    return useMutation<CreateClusterMutation, TError, CreateClusterMutationVariables, TContext>(
      {
    mutationKey: ['CreateCluster'],
    mutationFn: (variables?: CreateClusterMutationVariables) => graphqlFetcher<CreateClusterMutation, CreateClusterMutationVariables>(CreateClusterDocument, variables)(),
    ...options
  }
    )};

export const CreateEnvironmentDocument = `
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

export const useCreateEnvironmentMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateEnvironmentMutation, TError, CreateEnvironmentMutationVariables, TContext>) => {
    
    return useMutation<CreateEnvironmentMutation, TError, CreateEnvironmentMutationVariables, TContext>(
      {
    mutationKey: ['CreateEnvironment'],
    mutationFn: (variables?: CreateEnvironmentMutationVariables) => graphqlFetcher<CreateEnvironmentMutation, CreateEnvironmentMutationVariables>(CreateEnvironmentDocument, variables)(),
    ...options
  }
    )};

export const CreateRestoreDocument = `
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

export const useCreateRestoreMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateRestoreMutation, TError, CreateRestoreMutationVariables, TContext>) => {
    
    return useMutation<CreateRestoreMutation, TError, CreateRestoreMutationVariables, TContext>(
      {
    mutationKey: ['CreateRestore'],
    mutationFn: (variables?: CreateRestoreMutationVariables) => graphqlFetcher<CreateRestoreMutation, CreateRestoreMutationVariables>(CreateRestoreDocument, variables)(),
    ...options
  }
    )};

export const DeleteBackupDocument = `
    mutation DeleteBackup($backupId: UUID!) {
  deleteBackup(backupId: $backupId)
}
    `;

export const useDeleteBackupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<DeleteBackupMutation, TError, DeleteBackupMutationVariables, TContext>) => {
    
    return useMutation<DeleteBackupMutation, TError, DeleteBackupMutationVariables, TContext>(
      {
    mutationKey: ['DeleteBackup'],
    mutationFn: (variables?: DeleteBackupMutationVariables) => graphqlFetcher<DeleteBackupMutation, DeleteBackupMutationVariables>(DeleteBackupDocument, variables)(),
    ...options
  }
    )};

export const DeleteBackupStorageLocationDocument = `
    mutation DeleteBackupStorageLocation($backupStorageLocationId: UUID!) {
  deleteBackupStorageLocation(backupStorageLocationId: $backupStorageLocationId)
}
    `;

export const useDeleteBackupStorageLocationMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<DeleteBackupStorageLocationMutation, TError, DeleteBackupStorageLocationMutationVariables, TContext>) => {
    
    return useMutation<DeleteBackupStorageLocationMutation, TError, DeleteBackupStorageLocationMutationVariables, TContext>(
      {
    mutationKey: ['DeleteBackupStorageLocation'],
    mutationFn: (variables?: DeleteBackupStorageLocationMutationVariables) => graphqlFetcher<DeleteBackupStorageLocationMutation, DeleteBackupStorageLocationMutationVariables>(DeleteBackupStorageLocationDocument, variables)(),
    ...options
  }
    )};

export const DeployDocument = `
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

export const useDeployMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<DeployMutation, TError, DeployMutationVariables, TContext>) => {
    
    return useMutation<DeployMutation, TError, DeployMutationVariables, TContext>(
      {
    mutationKey: ['Deploy'],
    mutationFn: (variables?: DeployMutationVariables) => graphqlFetcher<DeployMutation, DeployMutationVariables>(DeployDocument, variables)(),
    ...options
  }
    )};

export const GetBackupStorageLocationDocument = `
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

export const useGetBackupStorageLocationQuery = <
      TData = GetBackupStorageLocationQuery,
      TError = Error
    >(
      variables: GetBackupStorageLocationQueryVariables,
      options?: Omit<UseQueryOptions<GetBackupStorageLocationQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetBackupStorageLocationQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetBackupStorageLocationQuery, TError, TData>(
      {
    queryKey: ['GetBackupStorageLocation', variables],
    queryFn: graphqlFetcher<GetBackupStorageLocationQuery, GetBackupStorageLocationQueryVariables>(GetBackupStorageLocationDocument, variables),
    ...options
  }
    )};

useGetBackupStorageLocationQuery.getKey = (variables: GetBackupStorageLocationQueryVariables) => ['GetBackupStorageLocation', variables];

export const GetClusterDocument = `
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

export const useGetClusterQuery = <
      TData = GetClusterQuery,
      TError = Error
    >(
      variables: GetClusterQueryVariables,
      options?: Omit<UseQueryOptions<GetClusterQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetClusterQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetClusterQuery, TError, TData>(
      {
    queryKey: ['GetCluster', variables],
    queryFn: graphqlFetcher<GetClusterQuery, GetClusterQueryVariables>(GetClusterDocument, variables),
    ...options
  }
    )};

useGetClusterQuery.getKey = (variables: GetClusterQueryVariables) => ['GetCluster', variables];

export const GetDeploymentDocument = `
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
    deployedServices {
      id
      driverServiceName
      resolvedName
      kind
      port
      primaryFqdn
      humanReadableFqdn
    }
  }
}
    `;

export const useGetDeploymentQuery = <
      TData = GetDeploymentQuery,
      TError = Error
    >(
      variables: GetDeploymentQueryVariables,
      options?: Omit<UseQueryOptions<GetDeploymentQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetDeploymentQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetDeploymentQuery, TError, TData>(
      {
    queryKey: ['GetDeployment', variables],
    queryFn: graphqlFetcher<GetDeploymentQuery, GetDeploymentQueryVariables>(GetDeploymentDocument, variables),
    ...options
  }
    )};

useGetDeploymentQuery.getKey = (variables: GetDeploymentQueryVariables) => ['GetDeployment', variables];

export const GetDeploymentTimelineDocument = `
    query GetDeploymentTimeline($deploymentId: UUID!) {
  deploymentTimeline(deploymentId: $deploymentId) {
    task {
      id
      type
      status
      message
      createdOn
      updatedOn
    }
    applicationVersion
    contextDiff {
      changes {
        path
        action
        oldValue
        newValue
      }
    }
  }
}
    `;

export const useGetDeploymentTimelineQuery = <
      TData = GetDeploymentTimelineQuery,
      TError = Error
    >(
      variables: GetDeploymentTimelineQueryVariables,
      options?: Omit<UseQueryOptions<GetDeploymentTimelineQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetDeploymentTimelineQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetDeploymentTimelineQuery, TError, TData>(
      {
    queryKey: ['GetDeploymentTimeline', variables],
    queryFn: graphqlFetcher<GetDeploymentTimelineQuery, GetDeploymentTimelineQueryVariables>(GetDeploymentTimelineDocument, variables),
    ...options
  }
    )};

useGetDeploymentTimelineQuery.getKey = (variables: GetDeploymentTimelineQueryVariables) => ['GetDeploymentTimeline', variables];

export const GetDriverDocument = `
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

export const useGetDriverQuery = <
      TData = GetDriverQuery,
      TError = Error
    >(
      variables: GetDriverQueryVariables,
      options?: Omit<UseQueryOptions<GetDriverQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetDriverQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetDriverQuery, TError, TData>(
      {
    queryKey: ['GetDriver', variables],
    queryFn: graphqlFetcher<GetDriverQuery, GetDriverQueryVariables>(GetDriverDocument, variables),
    ...options
  }
    )};

useGetDriverQuery.getKey = (variables: GetDriverQueryVariables) => ['GetDriver', variables];

export const GetEnvironmentDocument = `
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
      internal
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

export const useGetEnvironmentQuery = <
      TData = GetEnvironmentQuery,
      TError = Error
    >(
      variables: GetEnvironmentQueryVariables,
      options?: Omit<UseQueryOptions<GetEnvironmentQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetEnvironmentQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetEnvironmentQuery, TError, TData>(
      {
    queryKey: ['GetEnvironment', variables],
    queryFn: graphqlFetcher<GetEnvironmentQuery, GetEnvironmentQueryVariables>(GetEnvironmentDocument, variables),
    ...options
  }
    )};

useGetEnvironmentQuery.getKey = (variables: GetEnvironmentQueryVariables) => ['GetEnvironment', variables];

export const GetRestoreDocument = `
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

export const useGetRestoreQuery = <
      TData = GetRestoreQuery,
      TError = Error
    >(
      variables: GetRestoreQueryVariables,
      options?: Omit<UseQueryOptions<GetRestoreQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetRestoreQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetRestoreQuery, TError, TData>(
      {
    queryKey: ['GetRestore', variables],
    queryFn: graphqlFetcher<GetRestoreQuery, GetRestoreQueryVariables>(GetRestoreDocument, variables),
    ...options
  }
    )};

useGetRestoreQuery.getKey = (variables: GetRestoreQueryVariables) => ['GetRestore', variables];

export const GetTaskDocument = `
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

export const useGetTaskQuery = <
      TData = GetTaskQuery,
      TError = Error
    >(
      variables: GetTaskQueryVariables,
      options?: Omit<UseQueryOptions<GetTaskQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetTaskQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetTaskQuery, TError, TData>(
      {
    queryKey: ['GetTask', variables],
    queryFn: graphqlFetcher<GetTaskQuery, GetTaskQueryVariables>(GetTaskDocument, variables),
    ...options
  }
    )};

useGetTaskQuery.getKey = (variables: GetTaskQueryVariables) => ['GetTask', variables];

export const ListApplicationDriversDocument = `
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

export const useListApplicationDriversQuery = <
      TData = ListApplicationDriversQuery,
      TError = Error
    >(
      variables?: ListApplicationDriversQueryVariables,
      options?: Omit<UseQueryOptions<ListApplicationDriversQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListApplicationDriversQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListApplicationDriversQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['ListApplicationDrivers'] : ['ListApplicationDrivers', variables],
    queryFn: graphqlFetcher<ListApplicationDriversQuery, ListApplicationDriversQueryVariables>(ListApplicationDriversDocument, variables),
    ...options
  }
    )};

useListApplicationDriversQuery.getKey = (variables?: ListApplicationDriversQueryVariables) => variables === undefined ? ['ListApplicationDrivers'] : ['ListApplicationDrivers', variables];

export const ListBackupStorageLocationsDocument = `
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

export const useListBackupStorageLocationsQuery = <
      TData = ListBackupStorageLocationsQuery,
      TError = Error
    >(
      variables?: ListBackupStorageLocationsQueryVariables,
      options?: Omit<UseQueryOptions<ListBackupStorageLocationsQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListBackupStorageLocationsQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListBackupStorageLocationsQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['ListBackupStorageLocations'] : ['ListBackupStorageLocations', variables],
    queryFn: graphqlFetcher<ListBackupStorageLocationsQuery, ListBackupStorageLocationsQueryVariables>(ListBackupStorageLocationsDocument, variables),
    ...options
  }
    )};

useListBackupStorageLocationsQuery.getKey = (variables?: ListBackupStorageLocationsQueryVariables) => variables === undefined ? ['ListBackupStorageLocations'] : ['ListBackupStorageLocations', variables];

export const ListBackupsDocument = `
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

export const useListBackupsQuery = <
      TData = ListBackupsQuery,
      TError = Error
    >(
      variables: ListBackupsQueryVariables,
      options?: Omit<UseQueryOptions<ListBackupsQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListBackupsQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListBackupsQuery, TError, TData>(
      {
    queryKey: ['ListBackups', variables],
    queryFn: graphqlFetcher<ListBackupsQuery, ListBackupsQueryVariables>(ListBackupsDocument, variables),
    ...options
  }
    )};

useListBackupsQuery.getKey = (variables: ListBackupsQueryVariables) => ['ListBackups', variables];

export const ListClustersDocument = `
    query ListClusters {
  clusters {
    id
    name
    config
  }
}
    `;

export const useListClustersQuery = <
      TData = ListClustersQuery,
      TError = Error
    >(
      variables?: ListClustersQueryVariables,
      options?: Omit<UseQueryOptions<ListClustersQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListClustersQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListClustersQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['ListClusters'] : ['ListClusters', variables],
    queryFn: graphqlFetcher<ListClustersQuery, ListClustersQueryVariables>(ListClustersDocument, variables),
    ...options
  }
    )};

useListClustersQuery.getKey = (variables?: ListClustersQueryVariables) => variables === undefined ? ['ListClusters'] : ['ListClusters', variables];

export const ListDriversDocument = `
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

export const useListDriversQuery = <
      TData = ListDriversQuery,
      TError = Error
    >(
      variables?: ListDriversQueryVariables,
      options?: Omit<UseQueryOptions<ListDriversQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListDriversQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListDriversQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['ListDrivers'] : ['ListDrivers', variables],
    queryFn: graphqlFetcher<ListDriversQuery, ListDriversQueryVariables>(ListDriversDocument, variables),
    ...options
  }
    )};

useListDriversQuery.getKey = (variables?: ListDriversQueryVariables) => variables === undefined ? ['ListDrivers'] : ['ListDrivers', variables];

export const ListEnvironmentsDocument = `
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
      internal
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

export const useListEnvironmentsQuery = <
      TData = ListEnvironmentsQuery,
      TError = Error
    >(
      variables?: ListEnvironmentsQueryVariables,
      options?: Omit<UseQueryOptions<ListEnvironmentsQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListEnvironmentsQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListEnvironmentsQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['ListEnvironments'] : ['ListEnvironments', variables],
    queryFn: graphqlFetcher<ListEnvironmentsQuery, ListEnvironmentsQueryVariables>(ListEnvironmentsDocument, variables),
    ...options
  }
    )};

useListEnvironmentsQuery.getKey = (variables?: ListEnvironmentsQueryVariables) => variables === undefined ? ['ListEnvironments'] : ['ListEnvironments', variables];

export const ListRestoresDocument = `
    query ListRestores($backupId: UUID!, $status: RestoreStatus) {
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

export const useListRestoresQuery = <
      TData = ListRestoresQuery,
      TError = Error
    >(
      variables: ListRestoresQueryVariables,
      options?: Omit<UseQueryOptions<ListRestoresQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListRestoresQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListRestoresQuery, TError, TData>(
      {
    queryKey: ['ListRestores', variables],
    queryFn: graphqlFetcher<ListRestoresQuery, ListRestoresQueryVariables>(ListRestoresDocument, variables),
    ...options
  }
    )};

useListRestoresQuery.getKey = (variables: ListRestoresQueryVariables) => ['ListRestores', variables];

export const LoadLocalDriverDocument = `
    mutation LoadLocalDriver($path: String!) {
  loadLocalApplicationDriverVersion(path: $path) {
    id
    version
    applicationDriverId
  }
}
    `;

export const useLoadLocalDriverMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<LoadLocalDriverMutation, TError, LoadLocalDriverMutationVariables, TContext>) => {
    
    return useMutation<LoadLocalDriverMutation, TError, LoadLocalDriverMutationVariables, TContext>(
      {
    mutationKey: ['LoadLocalDriver'],
    mutationFn: (variables?: LoadLocalDriverMutationVariables) => graphqlFetcher<LoadLocalDriverMutation, LoadLocalDriverMutationVariables>(LoadLocalDriverDocument, variables)(),
    ...options
  }
    )};

export const LoadRemoteDriverDocument = `
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

export const useLoadRemoteDriverMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<LoadRemoteDriverMutation, TError, LoadRemoteDriverMutationVariables, TContext>) => {
    
    return useMutation<LoadRemoteDriverMutation, TError, LoadRemoteDriverMutationVariables, TContext>(
      {
    mutationKey: ['LoadRemoteDriver'],
    mutationFn: (variables?: LoadRemoteDriverMutationVariables) => graphqlFetcher<LoadRemoteDriverMutation, LoadRemoteDriverMutationVariables>(LoadRemoteDriverDocument, variables)(),
    ...options
  }
    )};

export const UnassignBackupStorageLocationDocument = `
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

export const useUnassignBackupStorageLocationMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<UnassignBackupStorageLocationMutation, TError, UnassignBackupStorageLocationMutationVariables, TContext>) => {
    
    return useMutation<UnassignBackupStorageLocationMutation, TError, UnassignBackupStorageLocationMutationVariables, TContext>(
      {
    mutationKey: ['UnassignBackupStorageLocation'],
    mutationFn: (variables?: UnassignBackupStorageLocationMutationVariables) => graphqlFetcher<UnassignBackupStorageLocationMutation, UnassignBackupStorageLocationMutationVariables>(UnassignBackupStorageLocationDocument, variables)(),
    ...options
  }
    )};

export const UpdateBackupStorageLocationDocument = `
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

export const useUpdateBackupStorageLocationMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<UpdateBackupStorageLocationMutation, TError, UpdateBackupStorageLocationMutationVariables, TContext>) => {
    
    return useMutation<UpdateBackupStorageLocationMutation, TError, UpdateBackupStorageLocationMutationVariables, TContext>(
      {
    mutationKey: ['UpdateBackupStorageLocation'],
    mutationFn: (variables?: UpdateBackupStorageLocationMutationVariables) => graphqlFetcher<UpdateBackupStorageLocationMutation, UpdateBackupStorageLocationMutationVariables>(UpdateBackupStorageLocationDocument, variables)(),
    ...options
  }
    )};

export const UpdateDeploymentVersionDocument = `
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

export const useUpdateDeploymentVersionMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<UpdateDeploymentVersionMutation, TError, UpdateDeploymentVersionMutationVariables, TContext>) => {
    
    return useMutation<UpdateDeploymentVersionMutation, TError, UpdateDeploymentVersionMutationVariables, TContext>(
      {
    mutationKey: ['UpdateDeploymentVersion'],
    mutationFn: (variables?: UpdateDeploymentVersionMutationVariables) => graphqlFetcher<UpdateDeploymentVersionMutation, UpdateDeploymentVersionMutationVariables>(UpdateDeploymentVersionDocument, variables)(),
    ...options
  }
    )};
