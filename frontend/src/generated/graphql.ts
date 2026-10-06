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

/** Affinity block (required + preferred) for one affinity kind. */
export type AffinityBlockInput = {
  preferred?: InputMaybe<Array<WeightedAffinityTermInput>>;
  replace?: InputMaybe<Scalars['Boolean']['input']>;
  required?: InputMaybe<Array<AffinityTermInput>>;
};

/** Single affinity term mirroring ``AffinityTerm``. */
export type AffinityTermInput = {
  deploymentRef?: InputMaybe<DeploymentReferenceInput>;
  labelSelector?: InputMaybe<LabelSelectorInput>;
  matchLabelKeys?: InputMaybe<Array<Scalars['String']['input']>>;
  mismatchLabelKeys?: InputMaybe<Array<Scalars['String']['input']>>;
  namespaceSelector?: InputMaybe<LabelSelectorInput>;
  namespaces?: InputMaybe<Array<Scalars['String']['input']>>;
  topologyKey: Scalars['String']['input'];
};

export type ApplicationDriver = {
  __typename?: 'ApplicationDriver';
  createdOn: Scalars['DateTime']['output'];
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
  /** Doc-only container-override declarations from the driver's spec.container_overrides block (014). Empty when the driver omits the block. */
  containerOverrides: Array<DriverContainerOverrideDoc>;
  contentHash?: Maybe<Scalars['String']['output']>;
  createdOn: Scalars['DateTime']['output'];
  defaultVersion?: Maybe<Scalars['String']['output']>;
  /** Doc-only env var declarations from the driver's spec.env_vars block. Empty when the driver omits the block. */
  envVars: Array<DriverEnvVarDoc>;
  helmChart: HelmChart;
  id: Scalars['UUID']['output'];
  parameters: Array<ParameterDefinition>;
  services: Array<ServiceDefinition>;
  sourceBranch?: Maybe<Scalars['String']['output']>;
  sourceCommitSha?: Maybe<Scalars['String']['output']>;
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
  /** Expiration reported by Velero for this backup. Null when no expiration was recorded — a backup Velero stored nothing for, or a backup taken before expiry was recorded. A backup whose status is FAILED can still carry an expiration: Velero's PartiallyFailed phase is stored, does expire, and is reported as FAILED here. */
  expiresAt?: Maybe<Scalars['DateTime']['output']>;
  id: Scalars['UUID']['output'];
  instance: ApplicationInstance;
  instanceId: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  sizeBytes?: Maybe<Scalars['Int']['output']>;
  startedAt?: Maybe<Scalars['DateTime']['output']>;
  status: Scalars['String']['output'];
  /** Retention TTL applied to this backup when it was created (e.g. ``"2160h"``). Null for backups taken before retention was recorded. */
  ttl?: Maybe<Scalars['String']['output']>;
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
  /** The component container declared by the deployment's pinned driver version, or null when it declares none. See `ComponentConfig.container`. */
  container?: Maybe<Scalars['String']['output']>;
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
  /** The component container the driver declares for this component (`components.<name>.container` in the driver specification file): the container that receives per-component post-render overrides such as env vars. Null when the driver declares none — component-scope env vars are then rejected and broader scopes skip this component. */
  container?: Maybe<Scalars['String']['output']>;
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
};

/** Per-component override block for a deployment: env vars, the container ``command``/``args``, and the component container's ``image``. Future per-component knobs (e.g. replicas) slot into this same input without a schema renumber. */
export type ComponentConfigInput = {
  /** Container args override for this component. Same shape and rules as ``command``, raising ``INVALID_CONTAINER_ARGS``. */
  args?: InputMaybe<Array<Scalars['String']['input']>>;
  /** Container entrypoint override for this component, scoped to this deployment. A non-empty list of strings; an empty list raises ``INVALID_CONTAINER_COMMAND``. Under full-replacement semantics ``null``/omitting it CLEARS the override (the chart/image default flows through) — clearing is never an empty list. Passed through verbatim — no templating. */
  command?: InputMaybe<Array<Scalars['String']['input']>>;
  /** Environment-variable overrides scoped to this component. Submitted as a list of ``{name, value}`` rows; duplicates within the list raise ``DUPLICATE_ENV_VAR_NAME`` with the component scope in the payload. Adding or changing a value on a component that declares no component container raises ``COMPONENT_CONTAINER_NOT_DECLARED``; removing values or re-submitting the stored ones unchanged is accepted. */
  envVars?: InputMaybe<Array<EnvVarInput>>;
  /** Image reference for this component's component container, scoped to this deployment. A full reference with an explicit tag or digest; every ``{{ app.version }}`` token is replaced with the deployment's application version at render time, and a literal tag pins the image. Under full-replacement semantics ``null``/omitting it CLEARS the override (the chart image applies). Raises ``UNKNOWN_COMPONENT_IMAGE_OVERRIDE``, ``INVALID_IMAGE_REFERENCE``, or ``COMPONENT_CONTAINER_NOT_DECLARED`` (adding or changing it on a component without a component container; removing it is always accepted). */
  image?: InputMaybe<Scalars['String']['input']>;
  /** The component name as declared by the deployment's currently pinned application-driver version. Must match a known component or the mutation raises ``UNKNOWN_COMPONENT_ENV_VAR``. Env vars on a component that declares no component container raise ``COMPONENT_CONTAINER_NOT_DECLARED`` (see ``envVars``). */
  name: Scalars['String']['input'];
};

/** The resolved container ``command``/``args`` override targeting one component of a deployment, plus an ``isOrphaned`` flag indicating whether the deployment's current driver still declares the targeted component. Orphaned blocks remain visible in the API but are NOT injected into rendered pods. ``command``/``args`` are ``null`` when no override is set for that slot (the chart default flows through). */
export type ComponentContainerOverrides = {
  __typename?: 'ComponentContainerOverrides';
  /** Resolved args override for this component, or ``null`` when unset (the chart/image default applies). */
  args?: Maybe<Array<Scalars['String']['output']>>;
  /** Resolved entrypoint override for this component, or ``null`` when unset (the chart/image default applies). */
  command?: Maybe<Array<Scalars['String']['output']>>;
  /** Name of the targeted component. */
  component: Scalars['String']['output'];
  /** True when the deployment's current driver no longer declares this component (the upgrade renamed or removed it). Orphaned blocks are visible in the API but are NOT injected into rendered pods, so the operator can audit and clean them up. */
  isOrphaned: Scalars['Boolean']['output'];
};

/** A bundle of environment variables targeting one component of a deployment. Applicable env vars are injected by a post-render patch into the component container the driver declares. ``isOrphaned`` flags blocks whose component the deployment's current driver no longer declares; ``isApplicable`` flags whether the env vars can reach any container. Non-applicable blocks remain visible in the API but are NOT injected into rendered pods. */
export type ComponentEnvVars = {
  __typename?: 'ComponentEnvVars';
  /** Name of the targeted component. */
  component: Scalars['String']['output'];
  /** The effective env vars set on this component (env+dep+component merged). */
  envVars: Array<EnvVar>;
  /** False when these env vars cannot reach any container: the component is orphaned (`isOrphaned`) or the driver declares no component container for it. Stored values are kept but not injected. */
  isApplicable: Scalars['Boolean']['output'];
  /** True when the deployment's current driver no longer declares this component (the upgrade renamed or removed it). Orphaned blocks are visible in the API but are NOT injected into rendered pods, so the user can audit and clean them up. */
  isOrphaned: Scalars['Boolean']['output'];
};

/** The image override for one component's component container. Orphaned or non-applicable overrides stay visible but are not rendered. */
export type ComponentImageOverride = {
  __typename?: 'ComponentImageOverride';
  /** Name of the targeted component. */
  component: Scalars['String']['output'];
  /** False when the override cannot reach a container: the component is orphaned (`isOrphaned`) or the driver declares no component container for it. The stored reference is kept but not rendered. */
  isApplicable: Scalars['Boolean']['output'];
  /** True when the deployment's current driver no longer declares this component (the upgrade renamed or removed it). */
  isOrphaned: Scalars['Boolean']['output'];
  /** The stored image reference, `{{ app.version }}` tokens included. */
  reference: Scalars['String']['output'];
  /** `reference` with every `{{ app.version }}` token replaced by the deployment's `applicationVersion`. */
  resolvedReference: Scalars['String']['output'];
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

export type CreateGroupInput = {
  memberIds?: InputMaybe<Array<Scalars['ID']['input']>>;
  name: Scalars['String']['input'];
  role: Role;
};

export type CreateUserInput = {
  displayName: Scalars['String']['input'];
  groupIds?: InputMaybe<Array<Scalars['ID']['input']>>;
  password: Scalars['String']['input'];
  role: Role;
  username: Scalars['String']['input'];
};

/** Dedicated per-environment ingress controller configuration. */
export type DedicatedIngressInput = {
  implementation?: InputMaybe<Scalars['String']['input']>;
  service?: InputMaybe<IngressServiceConfigInput>;
  type?: InputMaybe<Scalars['String']['input']>;
};

export type DeployedService = {
  __typename?: 'DeployedService';
  component: Scalars['String']['output'];
  deploymentId: Scalars['UUID']['output'];
  driverServiceName: Scalars['String']['output'];
  humanReadableFqdn?: Maybe<Scalars['String']['output']>;
  humanReadableUrl?: Maybe<Scalars['String']['output']>;
  id: Scalars['UUID']['output'];
  kind: Scalars['String']['output'];
  port: Scalars['Int']['output'];
  primaryFqdn?: Maybe<Scalars['String']['output']>;
  primaryUrl?: Maybe<Scalars['String']['output']>;
  resolvedName: Scalars['String']['output'];
  scope: Scalars['String']['output'];
};

export type Deployment = {
  __typename?: 'Deployment';
  applicationDriverVersion: ApplicationDriverVersion;
  applicationDriverVersionId: Scalars['UUID']['output'];
  applicationInstance?: Maybe<ApplicationInstance>;
  applicationVersion: Scalars['String']['output'];
  /** Per-component container ``command``/``args`` overrides, including orphaned blocks (``isOrphaned=true``). Component-scope only — there is NO environment/deployment layering. Live components with neither slot set are omitted to keep the surface tidy. Orphaned blocks (component renamed or removed by a driver upgrade — FR-005) are always surfaced here but skipped by the renderer so no value reaches a rendered pod. Cleared slots are returned as ``null``. */
  componentContainerOverrides: Array<ComponentContainerOverrides>;
  /** Per-component effective env vars, including orphaned blocks (``isOrphaned=true``). Component-level entries override deployment- and environment-level entries on a per-key basis (FR-002 deepest-wins). Non-applicable blocks (``isApplicable=false``: component renamed or removed by a driver upgrade, or no component container declared) are visible here but skipped by the post-render injector so no env entries reach rendered pods. */
  componentEnvVars: Array<ComponentEnvVars>;
  /** Per-component image overrides: live components by name, then orphaned blocks (``isOrphaned=true``) by name. Components without an override are omitted. */
  componentImageOverrides: Array<ComponentImageOverride>;
  components: Array<Component>;
  config: Scalars['JSON']['output'];
  crdStatus?: Maybe<DeploymentStatusType>;
  createdBy: User;
  /** Username of the user who created this deployment, or ``null`` if the creator row has been removed (forward-compatible with ``ondelete=SET NULL`` even though the FK is currently non-null). Unlike ``createdBy``, this field is NOT admin-gated — drivers and the UI can surface attribution without elevated access per FR-028. */
  createdByUsername?: Maybe<Scalars['String']['output']>;
  deletedAt?: Maybe<Scalars['DateTime']['output']>;
  deployedServices: Array<DeployedService>;
  /** Effective deployment-level env vars (after merging environment & deployment scopes, but BEFORE component-level overrides). Empty when none are set. */
  envVars: Array<EnvVar>;
  environment: Environment;
  environmentId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  internal: Scalars['Boolean']['output'];
  name: Scalars['String']['output'];
  parameters: Scalars['JSON']['output'];
  podStatuses: Array<PodStatus>;
  resolvedScheduling: Array<ResolvedComponentScheduling>;
  status: Scalars['String']['output'];
};

/** Typed deployment-configuration payload shared by the ``deploy`` (create) and ``updateDeployment`` mutations. Mirrors the source-of-truth ``DeploymentConfig`` Pydantic model field-for-field so both mutations accept an identical config shape. */
export type DeploymentConfigInput = {
  /** Retention applied to backups taken for this deployment, as a strictly positive Go duration in ``h``/``m``/``s`` units (e.g. ``"720h"``). Overrides the environment- and cluster-scope policy (deepest scope wins). Omitted means this deployment sets no policy and inherits the shallower scope, ultimately the built-in 720h default. */
  backupTtl?: InputMaybe<Scalars['String']['input']>;
  /** Full-replacement list of per-component override blocks. Flattened by the resolver to a dict keyed on ``name``; duplicate names raise ``DUPLICATE_COMPONENT_NAME``. An empty list explicitly clears every per-component block. */
  components?: InputMaybe<Array<ComponentConfigInput>>;
  /** Default database size hint applied to managed-database components in this deployment. */
  dbSize?: InputMaybe<Scalars['String']['input']>;
  /** Dedicated per-environment ingress controller configuration for this deployment. */
  dedicatedIngress?: InputMaybe<DedicatedIngressInput>;
  /** Deployment-scoped environment variables. Submitted as a list of ``{name, value}`` rows; duplicates raise ``DUPLICATE_ENV_VAR_NAME`` with the ``"deployment"`` scope in the payload. */
  envVars?: InputMaybe<Array<EnvVarInput>>;
  /** Endpoint source type used by external-DNS when publishing records for services in this deployment. */
  externalDnsEndpointsType?: InputMaybe<ExternalDnsEndpointsType>;
  /** Port used when constructing external URLs for services in this deployment. Pydantic enforces ``1 <= port <= 65535`` at validation time. */
  externalUrlPort?: InputMaybe<Scalars['Int']['input']>;
  /** URL scheme (``http`` or ``https``) used when constructing external URLs for services in this deployment. */
  externalUrlScheme?: InputMaybe<ExternalUrlScheme>;
  /** Fast storage configuration (Kubernetes ``StorageClass`` for the fast / NVMe tier) used by this deployment. */
  fastStorage?: InputMaybe<FastStorageInput>;
  /** Suffix appended to the auto-derived FQDN for every service in this deployment. */
  fqdnSuffix?: InputMaybe<Scalars['String']['input']>;
  /** Name of the IngressClass used by services in this deployment. */
  ingressClass?: InputMaybe<Scalars['String']['input']>;
  /** CIDR allowlist applied at the ingress layer. An empty list explicitly clears the persisted allowlist. */
  ipWhitelist?: InputMaybe<Array<Scalars['String']['input']>>;
  /** Node-selector expression applied to pods in this deployment. */
  nodeSelector?: InputMaybe<Scalars['String']['input']>;
  /** Kubernetes RuntimeClass name applied to pods in this deployment. */
  runtimeClass?: InputMaybe<Scalars['String']['input']>;
  /** Hierarchical pod scheduling & resource configuration (affinities, tolerations, topology spread, resource requests/limits, runtime class, post-render injection opt-outs). */
  scheduling?: InputMaybe<SchedulingInput>;
  /** Standard storage configuration (default Kubernetes ``StorageClass``) used by this deployment. */
  standardStorage?: InputMaybe<StandardStorageInput>;
};

export type DeploymentPodStatusReport = {
  deploymentId: Scalars['UUID']['input'];
  pods: Array<PodStatusInput>;
};

/** Reference to another deployment in the same environment. */
export type DeploymentReferenceInput = {
  components?: InputMaybe<Array<Scalars['String']['input']>>;
  deploymentId?: InputMaybe<Scalars['String']['input']>;
  deploymentName?: InputMaybe<Scalars['String']['input']>;
};

/** The declared state of one deployment captured at backup time — enough to recreate it later (clone readiness). */
export type DeploymentSnapshot = {
  __typename?: 'DeploymentSnapshot';
  applicationVersion: Scalars['String']['output'];
  config?: Maybe<Scalars['JSON']['output']>;
  deploymentId: Scalars['UUID']['output'];
  deploymentName: Scalars['String']['output'];
  driverFingerprint?: Maybe<Scalars['String']['output']>;
  driverName: Scalars['String']['output'];
  driverVersion: Scalars['String']['output'];
  instanceId: Scalars['UUID']['output'];
  parameters?: Maybe<Scalars['JSON']['output']>;
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

/** Doc-only declaration that a component's container ``command``/``args`` are overridable per deployment (014-component-container-overrides). Surfaces in the driver detail view; informational only — it does not validate, default, or constrain operator-set override values (FR-010/FR-011). */
export type DriverContainerOverrideDoc = {
  __typename?: 'DriverContainerOverrideDoc';
  args: Scalars['Boolean']['output'];
  command: Scalars['Boolean']['output'];
  component: Scalars['String']['output'];
  container?: Maybe<Scalars['String']['output']>;
  description: Scalars['String']['output'];
};

/** Doc-only declaration of an env var the driver's app respects. Surfaces in the driver detail view; does not validate, default, or constrain operator-set values (FR-015). */
export type DriverEnvVarDoc = {
  __typename?: 'DriverEnvVarDoc';
  components: Array<Scalars['String']['output']>;
  description: Scalars['String']['output'];
  level: DriverEnvVarLevel;
  name: Scalars['String']['output'];
};

export type DriverEnvVarLevel =
  | 'COMPONENT'
  | 'DEPLOYMENT';

/**
 * A single environment variable to inject into rendered containers.
 *
 * WARNING: This surface is for non-secret values only. The platform stores values in plaintext and exposes them through any query that selects them. Do not store credentials, API keys, or other secret material here — use the dedicated secret env var path (separate ticket) once available.
 */
export type EnvVar = {
  __typename?: 'EnvVar';
  /** POSIX-portable env var name, matching ^[A-Za-z_][A-Za-z0-9_]*$. */
  name: Scalars['String']['output'];
  /** The value to set. May be the empty string. NOT for secret material; see the EnvVar type description. */
  value: Scalars['String']['output'];
};

/** A single environment variable name/value pair. */
export type EnvVarInput = {
  name: Scalars['String']['input'];
  value: Scalars['String']['input'];
};

export type Environment = {
  __typename?: 'Environment';
  backupStorageLocation?: Maybe<BackupStorageLocation>;
  capabilities: Scalars['JSON']['output'];
  /** The clone that created this environment, or null when it was not clone-born. The provenance back-reference: `environmentClones` is scoped by *source* environment, so this is how a cloned environment points back at where it came from — and it keeps working after the source environment is deleted, since a terminal clone survives with `sourceEnvironmentName` intact. */
  clonedFrom?: Maybe<EnvironmentClone>;
  cluster: Cluster;
  config: Scalars['JSON']['output'];
  deployments: Array<Deployment>;
  /**
   * Env vars set at the environment scope. Empty when none are set.
   *
   * WARNING: This surface is for non-secret values only. The platform stores values in plaintext and exposes them through any query that selects them. Do not store credentials, API keys, or other secret material here — use the dedicated secret env var path (separate ticket) once available.
   */
  envVars: Array<EnvVar>;
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
};


export type EnvironmentDeploymentsArgs = {
  includeDeleted?: Scalars['Boolean']['input'];
};

export type EnvironmentBackup = {
  __typename?: 'EnvironmentBackup';
  /** One entry per eligible deployment: its constituent backup, its creation error, or neither when the constituent was deleted. */
  constituents: Array<EnvironmentBackupConstituent>;
  createdOn: Scalars['DateTime']['output'];
  /** Per-deployment declared state captured at backup time (clone readiness). */
  deploymentSnapshots: Array<DeploymentSnapshot>;
  environment: Environment;
  /** Environment config captured at backup time. */
  environmentConfig?: Maybe<Scalars['JSON']['output']>;
  environmentId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  /** Coordinated restores performed from this snapshot, newest first. */
  restores: Array<EnvironmentRestore>;
  /** Derived from the constituent backups and recorded creation errors on every read — never stored, so it cannot contradict its constituents. An environment with no eligible deployments yields a config-only snapshot that is COMPLETED immediately. */
  status: EnvironmentBackupStatus;
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

/** One eligible deployment's outcome in the snapshot. ``backup`` is set when a constituent backup exists, ``error`` when creation failed. Both null means the constituent was deleted individually after the snapshot was taken — the gap is deliberately visible. */
export type EnvironmentBackupConstituent = {
  __typename?: 'EnvironmentBackupConstituent';
  backup?: Maybe<Backup>;
  deploymentId: Scalars['UUID']['output'];
  deploymentName: Scalars['String']['output'];
  error?: Maybe<Scalars['String']['output']>;
};

export type EnvironmentBackupStatus =
  | 'COMPLETED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'PARTIAL'
  | 'PENDING';

export type EnvironmentClone = {
  __typename?: 'EnvironmentClone';
  /** The captured-config field names removed before the override merge, as supplied; null if none (FR-006). */
  clearConfigFields?: Maybe<Array<Scalars['String']['output']>>;
  /** Operation-level events that happened outside any single deployment (capture failed, target name lost, environment creation failed, an input deleted underneath the clone), rendered ``step: error``. Per-deployment failures are not here — they are in ``deploymentResults``. */
  cloneErrors: Array<Scalars['String']['output']>;
  /** The environment-config override as supplied, canonicalised; null if none. Merged over the captured config by the clone flow (FR-006). */
  configOverride?: Maybe<Scalars['JSON']['output']>;
  /** The environment the clone created. Null until the capture succeeds and the environment materialises, and again once it has been deleted (the discard path — SC-005). */
  createdEnvironment?: Maybe<Environment>;
  createdOn: Scalars['DateTime']['output'];
  /** One entry per source deployment considered — cloned, skipped with a reason, or failed with a reason (SC-003). */
  deploymentResults: Array<EnvironmentCloneDeploymentResult>;
  /** The capture the clone was built from. Null when registration never linked one, or once the capture has been deleted post-terminality (routine TTL cleanup does not rewrite the clone's outcome). */
  environmentBackup?: Maybe<EnvironmentBackup>;
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  /** The explicit deployment selection as requested. Null means every eligible deployment was included (FR-003). */
  requestedDeploymentIds?: Maybe<Array<Scalars['UUID']['output']>>;
  /** The environment that was cloned. Null once the source has been deleted — a terminal clone survives its source as the created environment's provenance (``sourceEnvironmentName`` keeps it readable). */
  sourceEnvironment?: Maybe<Environment>;
  sourceEnvironmentName: Scalars['String']['output'];
  /** Derived on every read from the capture's own derived status, the existence of the created environment, the constituent cross-target restores and the recorded clone errors — never stored, so it cannot contradict any of them. Terminal values are COMPLETED, PARTIAL and FAILED. */
  status: EnvironmentCloneStatus;
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

/** What became of one source deployment in a clone. ``PENDING`` is the transient value between registration and the step landing; a terminal clone contains no ``PENDING`` entry. Closed enum on the wire because the write-side vocabulary is fixed at these four values. */
export type EnvironmentCloneDeploymentOutcome =
  | 'CLONED'
  | 'FAILED'
  | 'PENDING'
  | 'SKIPPED';

/** One source deployment's outcome in the clone. Every source deployment considered appears exactly once (SC-003). ``reason`` is set for SKIPPED and FAILED and is open text — render it, do not switch on it. ``counterpartDeploymentId`` is the deployment created in the cloned environment (null unless CLONED); ``restoreId`` is the cross-target restore carrying the data (null until one is dispatched). */
export type EnvironmentCloneDeploymentResult = {
  __typename?: 'EnvironmentCloneDeploymentResult';
  counterpartDeploymentId?: Maybe<Scalars['UUID']['output']>;
  deploymentId: Scalars['UUID']['output'];
  deploymentName: Scalars['String']['output'];
  outcome: EnvironmentCloneDeploymentOutcome;
  reason?: Maybe<Scalars['String']['output']>;
  restoreId?: Maybe<Scalars['UUID']['output']>;
};

/** Derived status of an environment clone — recomputed on every read, never stored (FR-009). Same vocabulary as ``EnvironmentBackupStatus`` and ``EnvironmentRestoreStatus``, but folded from different inputs: the backing capture's own derived status, whether the created environment exists, the constituent cross-target restores, and the recorded clone errors. */
export type EnvironmentCloneStatus =
  | 'COMPLETED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'PARTIAL'
  | 'PENDING';

export type EnvironmentRestore = {
  __typename?: 'EnvironmentRestore';
  createdOn: Scalars['DateTime']['output'];
  environmentBackup: EnvironmentBackup;
  environmentBackupId: Scalars['UUID']['output'];
  id: Scalars['UUID']['output'];
  /** Constituent restores dispatched by this operation. */
  restores: Array<Restore>;
  /** Constituents not restored, each with its deployment name and reason (zero silent skips). */
  skippedConstituents: Array<SkippedConstituent>;
  /** Derived from the constituent restores and the recorded skips on every read — never stored, so it cannot contradict its constituents. A restore that skipped everything and restored nothing is FAILED; a restore with nothing to do at all (no constituents, no skips) is COMPLETED. */
  status: EnvironmentRestoreStatus;
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
};

/** Derived status of an environment restore. Mirrors ``EnvironmentBackupStatus`` — both project the same service-layer ``EnvironmentOperationStatus``. */
export type EnvironmentRestoreStatus =
  | 'COMPLETED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'PARTIAL'
  | 'PENDING';

export type ExternalDnsEndpointsType =
  | 'CLUSTER_IP'
  | 'NODE_EXTERNAL_IP';

export type ExternalUrlScheme =
  | 'HTTP'
  | 'HTTPS';

/** Fast storage configuration for the cluster, naming the Kubernetes ``StorageClass`` used as the fast (typically NVMe / local SSD) storage option for deployments. */
export type FastStorageInput = {
  /** The Kubernetes storage class name used as the fast storage option for this cluster. */
  storageClass: Scalars['String']['input'];
};

export type Group = {
  __typename?: 'Group';
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  role: Role;
};

export type HelmChart = {
  __typename?: 'HelmChart';
  id: Scalars['UUID']['output'];
  name: Scalars['String']['output'];
  repository: Scalars['String']['output'];
  valueTemplate: Scalars['String']['output'];
  version: Scalars['String']['output'];
};

/** Configuration for the dedicated ingress Kubernetes Service. */
export type IngressServiceConfigInput = {
  annotations?: InputMaybe<Scalars['JSON']['input']>;
  externalTrafficPolicy?: InputMaybe<Scalars['String']['input']>;
  ipFamilies?: InputMaybe<Array<Scalars['String']['input']>>;
  ipFamilyPolicy?: InputMaybe<Scalars['String']['input']>;
  loadBalancerIp?: InputMaybe<Scalars['String']['input']>;
  nodePort?: InputMaybe<Scalars['Int']['input']>;
  type?: InputMaybe<Scalars['String']['input']>;
};

/** Kubernetes-style label selector. */
export type LabelSelectorInput = {
  matchExpressions?: InputMaybe<Array<LabelSelectorRequirementInput>>;
  matchLabels?: InputMaybe<Scalars['JSON']['input']>;
};

export type LabelSelectorOperator =
  | 'DOES_NOT_EXIST'
  | 'EXISTS'
  | 'IN'
  | 'NOT_IN';

/** One ``matchExpressions`` entry on a label selector. */
export type LabelSelectorRequirementInput = {
  key: Scalars['String']['input'];
  operator: LabelSelectorOperator;
  values?: InputMaybe<Array<Scalars['String']['input']>>;
};

export type LoginResult = {
  __typename?: 'LoginResult';
  token: Scalars['String']['output'];
  user: User;
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
  changePassword: Scalars['Boolean']['output'];
  cloneEnvironment: EnvironmentClone;
  createBackup?: Maybe<Backup>;
  createBackupSchedule?: Maybe<BackupSchedule>;
  createBackupStorageLocation?: Maybe<BackupStorageLocation>;
  createCluster?: Maybe<Cluster>;
  createEnvironment?: Maybe<Environment>;
  createEnvironmentBackup: EnvironmentBackup;
  createGroup: Group;
  createRestore?: Maybe<Restore>;
  createUser: User;
  deleteBackup?: Maybe<Scalars['String']['output']>;
  deleteBackupSchedule?: Maybe<Scalars['String']['output']>;
  deleteBackupStorageLocation?: Maybe<Scalars['String']['output']>;
  deleteCluster?: Maybe<Scalars['String']['output']>;
  deleteDeployment: Task;
  deleteEnvironment?: Maybe<Scalars['String']['output']>;
  deleteEnvironmentBackup: Scalars['Boolean']['output'];
  deleteGroup: Scalars['Boolean']['output'];
  deleteUser: Scalars['Boolean']['output'];
  deploy?: Maybe<Task>;
  loadLocalApplicationDriverVersion?: Maybe<ApplicationDriverVersion>;
  loadRemoteApplicationDriverVersion?: Maybe<ApplicationDriverVersion>;
  login: LoginResult;
  logout: Scalars['Boolean']['output'];
  /** Record a step event. Called by Styrmin's own flows and actions with the action token. */
  recordStep: Step;
  reportDeploymentStatuses: ReportDeploymentStatusesResponse;
  reportPodStatuses: ReportPodStatusesResponse;
  resetUserPassword: Scalars['Boolean']['output'];
  restoreEnvironmentBackup: EnvironmentRestore;
  runJob?: Maybe<Task>;
  startComponents?: Maybe<Task>;
  stopComponents?: Maybe<Task>;
  unassignBackupStorageLocation?: Maybe<Environment>;
  updateBackupSchedule?: Maybe<BackupSchedule>;
  updateBackupStorageLocation?: Maybe<BackupStorageLocation>;
  updateDeployment?: Maybe<Task>;
  updateDeploymentVersion?: Maybe<Task>;
  updateEnvironment?: Maybe<Environment>;
  updateGroup: Group;
  updateUser: User;
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


export type MutationChangePasswordArgs = {
  currentPassword: Scalars['String']['input'];
  newPassword: Scalars['String']['input'];
};


export type MutationCloneEnvironmentArgs = {
  clearConfigFields?: InputMaybe<Array<Scalars['String']['input']>>;
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
  configOverride?: InputMaybe<UpdateEnvironmentInput>;
  deploymentIds?: InputMaybe<Array<Scalars['UUID']['input']>>;
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentName?: InputMaybe<Scalars['String']['input']>;
  name: Scalars['String']['input'];
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


export type MutationCreateEnvironmentBackupArgs = {
  environmentId: Scalars['UUID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
};


export type MutationCreateGroupArgs = {
  input: CreateGroupInput;
};


export type MutationCreateRestoreArgs = {
  backupId: Scalars['UUID']['input'];
  targetInstanceId?: InputMaybe<Scalars['UUID']['input']>;
  targetNamespace: Scalars['String']['input'];
};


export type MutationCreateUserArgs = {
  input: CreateUserInput;
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


export type MutationDeleteDeploymentArgs = {
  deploymentId: Scalars['UUID']['input'];
};


export type MutationDeleteEnvironmentArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentName?: InputMaybe<Scalars['String']['input']>;
};


export type MutationDeleteEnvironmentBackupArgs = {
  environmentBackupId: Scalars['UUID']['input'];
};


export type MutationDeleteGroupArgs = {
  id: Scalars['UUID']['input'];
};


export type MutationDeleteUserArgs = {
  id: Scalars['UUID']['input'];
};


export type MutationDeployArgs = {
  clusterId?: InputMaybe<Scalars['UUID']['input']>;
  clusterName?: InputMaybe<Scalars['String']['input']>;
  config?: InputMaybe<DeploymentConfigInput>;
  driver: Scalars['String']['input'];
  driverVersionId?: InputMaybe<Scalars['UUID']['input']>;
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentName?: InputMaybe<Scalars['String']['input']>;
  name?: InputMaybe<Scalars['String']['input']>;
  parameters?: InputMaybe<Array<ParameterValueInput>>;
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


export type MutationLoginArgs = {
  password: Scalars['String']['input'];
  username: Scalars['String']['input'];
};


export type MutationRecordStepArgs = {
  input: RecordStepInput;
};


export type MutationReportDeploymentStatusesArgs = {
  reports: Array<DeploymentStatusReportInput>;
};


export type MutationReportPodStatusesArgs = {
  reports: Array<DeploymentPodStatusReport>;
};


export type MutationResetUserPasswordArgs = {
  newPassword: Scalars['String']['input'];
  userId: Scalars['UUID']['input'];
};


export type MutationRestoreEnvironmentBackupArgs = {
  environmentBackupId: Scalars['UUID']['input'];
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
  deploymentId: Scalars['UUID']['input'];
  input: UpdateDeploymentInput;
};


export type MutationUpdateDeploymentVersionArgs = {
  deploymentId: Scalars['UUID']['input'];
  driverVersionId?: InputMaybe<Scalars['UUID']['input']>;
  parameters?: InputMaybe<Scalars['JSON']['input']>;
  version: Scalars['String']['input'];
};


export type MutationUpdateEnvironmentArgs = {
  environmentId: Scalars['UUID']['input'];
  input: UpdateEnvironmentInput;
};


export type MutationUpdateGroupArgs = {
  id: Scalars['UUID']['input'];
  input: UpdateGroupInput;
};


export type MutationUpdateUserArgs = {
  id: Scalars['UUID']['input'];
  input: UpdateUserInput;
};

export type ParameterDefinition = {
  __typename?: 'ParameterDefinition';
  default?: Maybe<Scalars['JSON']['output']>;
  kind: Scalars['String']['output'];
  label: Scalars['String']['output'];
  name: Scalars['String']['output'];
  values?: Maybe<Array<Scalars['String']['output']>>;
};

/** A single driver-defined parameter assignment. Parameter shapes are dynamic per driver version, so ``value`` remains JSON-typed. */
export type ParameterValueInput = {
  /** The name of the parameter as declared by the driver. */
  name: Scalars['String']['input'];
  /** The JSON-typed value to assign to the parameter. The driver's parameter definition determines the accepted value shape (string, integer, boolean, or enum) at validation time. */
  value: Scalars['JSON']['input'];
};

export type PodPhase =
  | 'FAILED'
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'UNKNOWN';

export type PodStatus = {
  __typename?: 'PodStatus';
  componentName?: Maybe<Scalars['String']['output']>;
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
  componentName?: InputMaybe<Scalars['String']['input']>;
  containerStatuses?: InputMaybe<Scalars['JSON']['input']>;
  namespace: Scalars['String']['input'];
  nodeName?: InputMaybe<Scalars['String']['input']>;
  phase: PodPhase;
  podName: Scalars['String']['input'];
  ready: Scalars['Boolean']['input'];
  restartCount: Scalars['Int']['input'];
  startedAt?: InputMaybe<Scalars['DateTime']['input']>;
};

/** Per-feature opt-out flags for the post-render injection. */
export type PostRenderInjectionInput = {
  nodeAffinity?: InputMaybe<Scalars['Boolean']['input']>;
  podAffinity?: InputMaybe<Scalars['Boolean']['input']>;
  resources?: InputMaybe<Scalars['Boolean']['input']>;
  runtimeClass?: InputMaybe<Scalars['Boolean']['input']>;
  tolerations?: InputMaybe<Scalars['Boolean']['input']>;
  topologySpread?: InputMaybe<Scalars['Boolean']['input']>;
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
  currentUser?: Maybe<User>;
  deployment?: Maybe<Deployment>;
  deploymentServices: Array<DeployedService>;
  deploymentTimeline: Array<DeploymentTimelineEntry>;
  environment?: Maybe<Environment>;
  environmentBackup?: Maybe<EnvironmentBackup>;
  environmentBackups: Array<EnvironmentBackup>;
  environmentClone: EnvironmentClone;
  environmentClones: Array<EnvironmentClone>;
  environmentRestore?: Maybe<EnvironmentRestore>;
  environmentRestores: Array<EnvironmentRestore>;
  environmentServices: Array<DeployedService>;
  environments: Array<Environment>;
  group?: Maybe<Group>;
  groups: Array<Group>;
  /** Health check probe */
  ok: Scalars['Boolean']['output'];
  podStatuses: Array<PodStatus>;
  restore?: Maybe<Restore>;
  restores: Array<Restore>;
  /** One step, for example to load its output. Any signed-in user. */
  step?: Maybe<Step>;
  task?: Maybe<Task>;
  tasks: Array<Task>;
  user?: Maybe<User>;
  users: Array<User>;
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
  deploymentId?: InputMaybe<Scalars['UUID']['input']>;
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  name?: InputMaybe<Scalars['String']['input']>;
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


export type QueryEnvironmentBackupArgs = {
  environmentBackupId: Scalars['UUID']['input'];
};


export type QueryEnvironmentBackupsArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type QueryEnvironmentCloneArgs = {
  environmentCloneId: Scalars['UUID']['input'];
};


export type QueryEnvironmentClonesArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type QueryEnvironmentRestoreArgs = {
  environmentRestoreId: Scalars['UUID']['input'];
};


export type QueryEnvironmentRestoresArgs = {
  environmentBackupId: Scalars['UUID']['input'];
};


export type QueryEnvironmentServicesArgs = {
  environmentId: Scalars['UUID']['input'];
};


export type QueryGroupArgs = {
  id: Scalars['UUID']['input'];
};


export type QueryGroupsArgs = {
  search?: InputMaybe<Scalars['String']['input']>;
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


export type QueryStepArgs = {
  stepId: Scalars['UUID']['input'];
};


export type QueryTaskArgs = {
  taskId: Scalars['UUID']['input'];
};


export type QueryUserArgs = {
  id: Scalars['UUID']['input'];
};


export type QueryUsersArgs = {
  active?: InputMaybe<Scalars['Boolean']['input']>;
  role?: InputMaybe<Role>;
  search?: InputMaybe<Scalars['String']['input']>;
};

export type RecordStepInput = {
  backupId?: InputMaybe<Scalars['UUID']['input']>;
  /** Required with FAILED. */
  error?: InputMaybe<Scalars['String']['input']>;
  event: StepEvent;
  key?: InputMaybe<Scalars['String']['input']>;
  kind?: InputMaybe<StepKind>;
  /** Required with STARTED when the step does not exist yet. */
  name?: InputMaybe<Scalars['String']['input']>;
  /** When the event happened, in the writer's clock. Defaults to the server's time. */
  occurredAt?: InputMaybe<Scalars['DateTime']['input']>;
  /** Used with OUTPUT, and allowed with FAILED. */
  output?: InputMaybe<Scalars['String']['input']>;
  outputTruncated?: Scalars['Boolean']['input'];
  restoreId?: InputMaybe<Scalars['UUID']['input']>;
  /** Address an existing step. Use instead of a parent and key. */
  stepId?: InputMaybe<Scalars['UUID']['input']>;
  taskId?: InputMaybe<Scalars['UUID']['input']>;
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

export type ResolvedComponentScheduling = {
  __typename?: 'ResolvedComponentScheduling';
  componentName: Scalars['String']['output'];
  config: Scalars['JSON']['output'];
  provenance: Scalars['JSON']['output'];
};

/** Container resource requirements (``requests`` and ``limits``). */
export type ResourceRequirementsInput = {
  limits?: InputMaybe<ResourceSpecInput>;
  requests?: InputMaybe<ResourceSpecInput>;
};

/** Pod-container resource ``requests`` or ``limits`` payload. */
export type ResourceSpecInput = {
  cpu?: InputMaybe<Scalars['String']['input']>;
  ephemeralStorage?: InputMaybe<Scalars['String']['input']>;
  extended?: InputMaybe<Scalars['JSON']['input']>;
  memory?: InputMaybe<Scalars['String']['input']>;
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

export type Role =
  | 'ADMIN'
  | 'READ_ONLY'
  | 'READ_WRITE';

/** Hierarchical pod scheduling & resource configuration section. */
export type SchedulingInput = {
  inject?: InputMaybe<PostRenderInjectionInput>;
  nodeAffinity?: InputMaybe<AffinityBlockInput>;
  podAffinity?: InputMaybe<AffinityBlockInput>;
  podAntiAffinity?: InputMaybe<AffinityBlockInput>;
  resources?: InputMaybe<ResourceRequirementsInput>;
  runtimeClass?: InputMaybe<Scalars['String']['input']>;
  tolerations?: InputMaybe<Array<TolerationInput>>;
  topologySpreadConstraints?: InputMaybe<Array<TopologySpreadConstraintInput>>;
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

/** A constituent that was not restored, attributed by deployment name and reason. `reason` is open text, not a closed vocabulary — render it, do not switch on it. Six values are conventional: backup failed at creation, backup not completed, backup deleted, backup expired, deployment no longer exists, deployment busy with another restore. Any other constituent-creation failure is reported verbatim as 'restore could not be created: <error>', and the set is expected to grow without a schema change. */
export type SkippedConstituent = {
  __typename?: 'SkippedConstituent';
  deploymentId: Scalars['UUID']['output'];
  deploymentName: Scalars['String']['output'];
  reason: Scalars['String']['output'];
};

/** Standard storage configuration for the cluster, naming the Kubernetes ``StorageClass`` used as the default for deployments. */
export type StandardStorageInput = {
  /** The Kubernetes storage class name used as the standard storage option for this cluster. */
  storageClass: Scalars['String']['input'];
};

/** One unit of work inside a task, a backup or a restore. */
export type Step = {
  __typename?: 'Step';
  attemptCount: Scalars['Int']['output'];
  backupId?: Maybe<Scalars['UUID']['output']>;
  /** FluxCD's current reason and message, HelmRelease step only. */
  detail?: Maybe<Scalars['String']['output']>;
  /** Seconds between startedAt and endedAt; null until both are set. */
  durationSeconds?: Maybe<Scalars['Float']['output']>;
  endedAt?: Maybe<Scalars['DateTime']['output']>;
  /** The newest error, or null. */
  error?: Maybe<Scalars['String']['output']>;
  /** The error of each failed attempt, oldest first. */
  errors: Array<StepError>;
  hasOutput: Scalars['Boolean']['output'];
  id: Scalars['UUID']['output'];
  key: Scalars['String']['output'];
  kind: StepKind;
  name: Scalars['String']['output'];
  /** Set while a running operator-phase step has had no agent report for more than 60 seconds. */
  noReportSince?: Maybe<Scalars['DateTime']['output']>;
  /** End of a failed command's output. Request it only for one step at a time. */
  output?: Maybe<Scalars['String']['output']>;
  outputTruncated: Scalars['Boolean']['output'];
  restoreId?: Maybe<Scalars['UUID']['output']>;
  rollbackMessage?: Maybe<Scalars['String']['output']>;
  rolledBackAt?: Maybe<Scalars['DateTime']['output']>;
  startedAt?: Maybe<Scalars['DateTime']['output']>;
  /** Tasks that this hook step started. */
  startedTasks: Array<Task>;
  status: StepStatus;
  /** The later task that interrupted this step. */
  supersededBy?: Maybe<Task>;
  taskId?: Maybe<Scalars['UUID']['output']>;
};

export type StepError = {
  __typename?: 'StepError';
  attempt: Scalars['Int']['output'];
  message: Scalars['String']['output'];
  occurredAt: Scalars['DateTime']['output'];
};

export type StepEvent =
  | 'FAILED'
  | 'OUTPUT'
  | 'STARTED'
  | 'SUCCEEDED';

export type StepKind =
  | 'BACKUP_COMPONENT'
  | 'COMMAND'
  | 'HOOK'
  | 'OPERATOR_PHASE'
  | 'PLAN'
  | 'RESOURCE_WRITE'
  | 'RESTORE';

export type StepStatus =
  | 'FAILED'
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'SUPERSEDED';

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

export type TolerationEffect =
  | 'NO_EXECUTE'
  | 'NO_SCHEDULE'
  | 'PREFER_NO_SCHEDULE';

/** Single pod toleration entry. */
export type TolerationInput = {
  effect?: InputMaybe<TolerationEffect>;
  key?: InputMaybe<Scalars['String']['input']>;
  operator?: InputMaybe<TolerationOperator>;
  tolerationSeconds?: InputMaybe<Scalars['Int']['input']>;
  value?: InputMaybe<Scalars['String']['input']>;
};

export type TolerationOperator =
  | 'EQUAL'
  | 'EXISTS';

/** One topology-spread constraint on the pod template. */
export type TopologySpreadConstraintInput = {
  labelSelector?: InputMaybe<LabelSelectorInput>;
  matchLabelKeys?: InputMaybe<Array<Scalars['String']['input']>>;
  maxSkew: Scalars['Int']['input'];
  minDomains?: InputMaybe<Scalars['Int']['input']>;
  nodeAffinityPolicy?: InputMaybe<Scalars['String']['input']>;
  nodeTaintsPolicy?: InputMaybe<Scalars['String']['input']>;
  topologyKey: Scalars['String']['input'];
  whenUnsatisfiable: WhenUnsatisfiable;
};

/** Full-replacement input for the ``updateDeployment`` mutation. Inherits every config field from ``DeploymentConfigInput`` (shared with the ``deploy`` create mutation) and adds the update-only ``name`` / ``parameters`` / ``serviceNameOverrides`` fields. Top-level fields use full-replacement semantics: an omitted (``null``) field means "do not touch the corresponding persisted state"; an empty list/dict means "explicitly clear". The single exception is ``parameters``, which uses merge semantics for backwards compatibility — entries in the input merge on top of the persisted parameters dict (existing keys not named in the input survive). */
export type UpdateDeploymentInput = {
  /** Retention applied to backups taken for this deployment, as a strictly positive Go duration in ``h``/``m``/``s`` units (e.g. ``"720h"``). Overrides the environment- and cluster-scope policy (deepest scope wins). Omitted means this deployment sets no policy and inherits the shallower scope, ultimately the built-in 720h default. */
  backupTtl?: InputMaybe<Scalars['String']['input']>;
  /** Full-replacement list of per-component override blocks. Flattened by the resolver to a dict keyed on ``name``; duplicate names raise ``DUPLICATE_COMPONENT_NAME``. An empty list explicitly clears every per-component block. */
  components?: InputMaybe<Array<ComponentConfigInput>>;
  /** Default database size hint applied to managed-database components in this deployment. */
  dbSize?: InputMaybe<Scalars['String']['input']>;
  /** Dedicated per-environment ingress controller configuration for this deployment. */
  dedicatedIngress?: InputMaybe<DedicatedIngressInput>;
  /** Deployment-scoped environment variables. Submitted as a list of ``{name, value}`` rows; duplicates raise ``DUPLICATE_ENV_VAR_NAME`` with the ``"deployment"`` scope in the payload. */
  envVars?: InputMaybe<Array<EnvVarInput>>;
  /** Endpoint source type used by external-DNS when publishing records for services in this deployment. */
  externalDnsEndpointsType?: InputMaybe<ExternalDnsEndpointsType>;
  /** Port used when constructing external URLs for services in this deployment. Pydantic enforces ``1 <= port <= 65535`` at validation time. */
  externalUrlPort?: InputMaybe<Scalars['Int']['input']>;
  /** URL scheme (``http`` or ``https``) used when constructing external URLs for services in this deployment. */
  externalUrlScheme?: InputMaybe<ExternalUrlScheme>;
  /** Fast storage configuration (Kubernetes ``StorageClass`` for the fast / NVMe tier) used by this deployment. */
  fastStorage?: InputMaybe<FastStorageInput>;
  /** Suffix appended to the auto-derived FQDN for every service in this deployment. */
  fqdnSuffix?: InputMaybe<Scalars['String']['input']>;
  /** Name of the IngressClass used by services in this deployment. */
  ingressClass?: InputMaybe<Scalars['String']['input']>;
  /** CIDR allowlist applied at the ingress layer. An empty list explicitly clears the persisted allowlist. */
  ipWhitelist?: InputMaybe<Array<Scalars['String']['input']>>;
  /** New name for the deployment. Omitted means "do not rename". */
  name?: InputMaybe<Scalars['String']['input']>;
  /** Node-selector expression applied to pods in this deployment. */
  nodeSelector?: InputMaybe<Scalars['String']['input']>;
  /** Driver-defined parameter assignments. **Merge semantics** (asymmetric with the rest of this input): entries in the list merge on top of the persisted parameters dict, so existing keys not named in the input survive. Duplicate ``name`` entries within the list raise ``DUPLICATE_PARAMETER_NAME``. */
  parameters?: InputMaybe<Array<ParameterValueInput>>;
  /** Kubernetes RuntimeClass name applied to pods in this deployment. */
  runtimeClass?: InputMaybe<Scalars['String']['input']>;
  /** Hierarchical pod scheduling & resource configuration (affinities, tolerations, topology spread, resource requests/limits, runtime class, post-render injection opt-outs). */
  scheduling?: InputMaybe<SchedulingInput>;
  /** Full-replacement list of service-name overrides applied at deploy time. Each entry maps a driver-declared service name to the operator-chosen override name. */
  serviceNameOverrides?: InputMaybe<Array<ServiceNameOverride>>;
  /** Standard storage configuration (default Kubernetes ``StorageClass``) used by this deployment. */
  standardStorage?: InputMaybe<StandardStorageInput>;
};

/** Full-replacement input for environment configuration updates. Submit the complete desired configuration; any field omitted (``null``) is persisted as its unset state on the underlying EnvironmentConfig. */
export type UpdateEnvironmentInput = {
  backupTtl?: InputMaybe<Scalars['String']['input']>;
  dbSize?: InputMaybe<Scalars['String']['input']>;
  dedicatedIngress?: InputMaybe<DedicatedIngressInput>;
  envVars?: InputMaybe<Array<EnvVarInput>>;
  externalDnsEndpointsType?: InputMaybe<ExternalDnsEndpointsType>;
  externalUrlPort?: InputMaybe<Scalars['Int']['input']>;
  externalUrlScheme?: InputMaybe<ExternalUrlScheme>;
  fqdnSuffix?: InputMaybe<Scalars['String']['input']>;
  ingressClass?: InputMaybe<Scalars['String']['input']>;
  ipWhitelist?: InputMaybe<Array<Scalars['String']['input']>>;
  scheduling?: InputMaybe<SchedulingInput>;
};

export type UpdateGroupInput = {
  memberIds?: InputMaybe<Array<Scalars['ID']['input']>>;
  name?: InputMaybe<Scalars['String']['input']>;
  role?: InputMaybe<Role>;
};

export type UpdateUserInput = {
  active?: InputMaybe<Scalars['Boolean']['input']>;
  displayName?: InputMaybe<Scalars['String']['input']>;
  groupIds?: InputMaybe<Array<Scalars['ID']['input']>>;
  role?: InputMaybe<Role>;
};

export type User = {
  __typename?: 'User';
  active: Scalars['Boolean']['output'];
  createdOn?: Maybe<Scalars['DateTime']['output']>;
  displayName: Scalars['String']['output'];
  effectiveRole: Role;
  groups: Array<Group>;
  id: Scalars['UUID']['output'];
  role: Role;
  updatedOn?: Maybe<Scalars['DateTime']['output']>;
  username: Scalars['String']['output'];
};

/** Weighted affinity term for a ``preferred`` rule. */
export type WeightedAffinityTermInput = {
  term: AffinityTermInput;
  weight: Scalars['Int']['input'];
};

export type WhenUnsatisfiable =
  | 'DO_NOT_SCHEDULE'
  | 'SCHEDULE_ANYWAY';

export type AssignBackupStorageLocationMutationVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
  backupStorageLocationId: Scalars['UUID']['input'];
}>;


export type AssignBackupStorageLocationMutation = { __typename?: 'Mutation', assignBackupStorageLocation?: { __typename?: 'Environment', id: string, name: string, backupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string } | null } | null };

export type ChangePasswordMutationVariables = Exact<{
  currentPassword: Scalars['String']['input'];
  newPassword: Scalars['String']['input'];
}>;


export type ChangePasswordMutation = { __typename?: 'Mutation', changePassword: boolean };

export type CloneEnvironmentMutationVariables = Exact<{
  name: Scalars['String']['input'];
  environmentId?: InputMaybe<Scalars['UUID']['input']>;
  deploymentIds?: InputMaybe<Array<Scalars['UUID']['input']> | Scalars['UUID']['input']>;
  configOverride?: InputMaybe<UpdateEnvironmentInput>;
  clearConfigFields?: InputMaybe<Array<Scalars['String']['input']> | Scalars['String']['input']>;
}>;


export type CloneEnvironmentMutation = { __typename?: 'Mutation', cloneEnvironment: { __typename?: 'EnvironmentClone', id: string, name: string, status: EnvironmentCloneStatus, createdOn: any } };

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

export type CreateEnvironmentBackupMutationVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
}>;


export type CreateEnvironmentBackupMutation = { __typename?: 'Mutation', createEnvironmentBackup: { __typename?: 'EnvironmentBackup', id: string, name: string, status: EnvironmentBackupStatus, createdOn: any } };

export type CreateGroupMutationVariables = Exact<{
  input: CreateGroupInput;
}>;


export type CreateGroupMutation = { __typename?: 'Mutation', createGroup: { __typename?: 'Group', id: string, name: string, role: Role } };

export type CreateRestoreMutationVariables = Exact<{
  backupId: Scalars['UUID']['input'];
  targetNamespace: Scalars['String']['input'];
  targetInstanceId?: InputMaybe<Scalars['UUID']['input']>;
}>;


export type CreateRestoreMutation = { __typename?: 'Mutation', createRestore?: { __typename?: 'Restore', id: string, name: string, status: string, backupId: string, targetNamespace: string, targetInstanceId?: string | null, errorMessage?: string | null, createdOn: any } | null };

export type CreateUserMutationVariables = Exact<{
  input: CreateUserInput;
}>;


export type CreateUserMutation = { __typename?: 'Mutation', createUser: { __typename?: 'User', id: string, username: string, displayName: string, role: Role, effectiveRole: Role, active: boolean, createdOn?: any | null, updatedOn?: any | null, groups: Array<{ __typename?: 'Group', id: string, name: string, role: Role }> } };

export type CurrentUserQueryVariables = Exact<{ [key: string]: never; }>;


export type CurrentUserQuery = { __typename?: 'Query', currentUser?: { __typename?: 'User', id: string, username: string, displayName: string, role: Role, effectiveRole: Role, active: boolean } | null };

export type DeleteBackupMutationVariables = Exact<{
  backupId: Scalars['UUID']['input'];
}>;


export type DeleteBackupMutation = { __typename?: 'Mutation', deleteBackup?: string | null };

export type DeleteBackupStorageLocationMutationVariables = Exact<{
  backupStorageLocationId: Scalars['UUID']['input'];
}>;


export type DeleteBackupStorageLocationMutation = { __typename?: 'Mutation', deleteBackupStorageLocation?: string | null };

export type DeleteDeploymentMutationVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
}>;


export type DeleteDeploymentMutation = { __typename?: 'Mutation', deleteDeployment: { __typename?: 'Task', id: string, type: string, status: string, deploymentId?: string | null } };

export type DeleteEnvironmentBackupMutationVariables = Exact<{
  environmentBackupId: Scalars['UUID']['input'];
}>;


export type DeleteEnvironmentBackupMutation = { __typename?: 'Mutation', deleteEnvironmentBackup: boolean };

export type DeleteGroupMutationVariables = Exact<{
  id: Scalars['UUID']['input'];
}>;


export type DeleteGroupMutation = { __typename?: 'Mutation', deleteGroup: boolean };

export type DeleteUserMutationVariables = Exact<{
  id: Scalars['UUID']['input'];
}>;


export type DeleteUserMutation = { __typename?: 'Mutation', deleteUser: boolean };

export type DeployMutationVariables = Exact<{
  version?: InputMaybe<Scalars['String']['input']>;
  driver: Scalars['String']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  environmentId: Scalars['UUID']['input'];
  config?: InputMaybe<DeploymentConfigInput>;
  parameters?: InputMaybe<Array<ParameterValueInput> | ParameterValueInput>;
  serviceNameOverrides?: InputMaybe<Array<ServiceNameOverride> | ServiceNameOverride>;
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


export type GetDeploymentQuery = { __typename?: 'Query', deployment?: { __typename?: 'Deployment', id: string, name: string, status: string, deletedAt?: any | null, config: Record<string, unknown>, parameters: Record<string, unknown>, applicationVersion: string, applicationDriverVersionId: string, environmentId: string, applicationDriverVersion: { __typename?: 'ApplicationDriverVersion', id: string, version: string, contentHash?: string | null, sourceCommitSha?: string | null, applicationDriver: { __typename?: 'ApplicationDriver', id: string, name: string }, parameters: Array<{ __typename?: 'ParameterDefinition', name: string, label: string, kind: string, default?: Record<string, unknown> | null, values?: Array<string> | null }> }, environment: { __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string, config: Record<string, unknown> } }, applicationInstance?: { __typename?: 'ApplicationInstance', id: string, name: string, status: string, applicationVersion: string, applicationDriverVersionId: string, deploymentId: string } | null, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean, container?: string | null }>, componentImageOverrides: Array<{ __typename?: 'ComponentImageOverride', component: string, reference: string, resolvedReference: string, isOrphaned: boolean, isApplicable: boolean }>, deployedServices: Array<{ __typename?: 'DeployedService', id: string, driverServiceName: string, resolvedName: string, kind: string, port: number, primaryFqdn?: string | null, humanReadableFqdn?: string | null, primaryUrl?: string | null, humanReadableUrl?: string | null }> } | null };

export type GetDeploymentPodsQueryVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
}>;


export type GetDeploymentPodsQuery = { __typename?: 'Query', podStatuses: Array<{ __typename?: 'PodStatus', id: string, podName: string, namespace: string, phase: PodPhase, ready: boolean, restartCount: number, nodeName?: string | null, componentName?: string | null, startedAt?: any | null, createdOn?: any | null, lastPolledAt?: any | null, containerStatuses: Record<string, unknown> }> };

export type GetDeploymentResolvedSchedulingQueryVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
}>;


export type GetDeploymentResolvedSchedulingQuery = { __typename?: 'Query', deployment?: { __typename?: 'Deployment', id: string, name: string, resolvedScheduling: Array<{ __typename?: 'ResolvedComponentScheduling', componentName: string, config: Record<string, unknown>, provenance: Record<string, unknown> }> } | null };

export type GetDeploymentTimelineQueryVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
}>;


export type GetDeploymentTimelineQuery = { __typename?: 'Query', deploymentTimeline: Array<{ __typename?: 'DeploymentTimelineEntry', applicationVersion?: string | null, task: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, createdOn?: any | null, updatedOn?: any | null }, contextDiff?: { __typename?: 'ContextDiff', changes: Array<{ __typename?: 'ContextChange', path: string, action: string, oldValue?: Record<string, unknown> | null, newValue?: Record<string, unknown> | null }> } | null }> };

export type GetDriverQueryVariables = Exact<{
  applicationDriverId: Scalars['UUID']['input'];
}>;


export type GetDriverQuery = { __typename?: 'Query', applicationDriver?: { __typename?: 'ApplicationDriver', id: string, name: string, createdOn: any, versions: Array<{ __typename?: 'ApplicationDriverVersion', id: string, version: string, supportedVersions: string, sourceType: string, sourceRepository: string, sourceBranch?: string | null, sourcePath?: string | null, sourceCommitSha?: string | null, contentHash?: string | null, components?: Record<string, unknown> | null, createdOn: any, parameters: Array<{ __typename?: 'ParameterDefinition', name: string, label: string, kind: string, default?: Record<string, unknown> | null, values?: Array<string> | null }>, componentConfigs: Array<{ __typename?: 'ComponentConfig', id: string, name: string, config?: Record<string, unknown> | null, container?: string | null }>, helmChart: { __typename?: 'HelmChart', id: string, name: string, version: string, repository: string, valueTemplate: string }, actions: Array<{ __typename?: 'Action', id: string, name: string, description: string, location: string }> }> } | null };

export type GetEnvironmentQueryVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
  includeDeleted?: InputMaybe<Scalars['Boolean']['input']>;
}>;


export type GetEnvironmentQuery = { __typename?: 'Query', environment?: { __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string }, backupStorageLocation?: { __typename?: 'BackupStorageLocation', id: string, name: string } | null, deployments: Array<{ __typename?: 'Deployment', id: string, name: string, status: string, deletedAt?: any | null, internal: boolean, applicationVersion: string, applicationDriverVersionId: string, applicationDriverVersion: { __typename?: 'ApplicationDriverVersion', version: string, contentHash?: string | null, sourceCommitSha?: string | null, applicationDriver: { __typename?: 'ApplicationDriver', name: string } }, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }>, applicationInstance?: { __typename?: 'ApplicationInstance', id: string, status: string } | null }> } | null };

export type GetEnvironmentCloneQueryVariables = Exact<{
  environmentCloneId: Scalars['UUID']['input'];
}>;


export type GetEnvironmentCloneQuery = { __typename?: 'Query', environmentClone: { __typename?: 'EnvironmentClone', id: string, name: string, status: EnvironmentCloneStatus, sourceEnvironmentName: string, createdOn: any, updatedOn?: any | null, requestedDeploymentIds?: Array<string> | null, configOverride?: Record<string, unknown> | null, clearConfigFields?: Array<string> | null, cloneErrors: Array<string>, sourceEnvironment?: { __typename?: 'Environment', id: string, name: string } | null, environmentBackup?: { __typename?: 'EnvironmentBackup', id: string, name: string, status: EnvironmentBackupStatus } | null, createdEnvironment?: { __typename?: 'Environment', id: string, name: string } | null, deploymentResults: Array<{ __typename?: 'EnvironmentCloneDeploymentResult', deploymentId: string, deploymentName: string, outcome: EnvironmentCloneDeploymentOutcome, reason?: string | null, counterpartDeploymentId?: string | null, restoreId?: string | null }> } };

export type GetGroupQueryVariables = Exact<{ [key: string]: never; }>;


export type GetGroupQuery = { __typename?: 'Query', groups: Array<{ __typename?: 'Group', id: string, name: string, role: Role }> };

export type GetRestoreQueryVariables = Exact<{
  restoreId: Scalars['UUID']['input'];
}>;


export type GetRestoreQuery = { __typename?: 'Query', restore?: { __typename?: 'Restore', id: string, name: string, status: string, createdOn: any, startedAt?: any | null, completedAt?: any | null, targetNamespace: string, errorMessage?: string | null, backupId: string, targetInstanceId?: string | null, componentStatuses?: Array<{ __typename?: 'ComponentRestoreStatus', componentName: string, status: string, errorMessage?: string | null }> | null } | null };

export type GetTaskQueryVariables = Exact<{
  taskId: Scalars['UUID']['input'];
}>;


export type GetTaskQuery = { __typename?: 'Query', task?: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, deploymentId?: string | null } | null };

export type ListApplicationDriversQueryVariables = Exact<{ [key: string]: never; }>;


export type ListApplicationDriversQuery = { __typename?: 'Query', applicationDrivers: Array<{ __typename?: 'ApplicationDriver', id: string, name: string, versions: Array<{ __typename?: 'ApplicationDriverVersion', id: string, version: string, supportedVersions: string, defaultVersion?: string | null, contentHash?: string | null, sourceCommitSha?: string | null, parameters: Array<{ __typename?: 'ParameterDefinition', name: string, label: string, kind: string, default?: Record<string, unknown> | null, values?: Array<string> | null }> }> }> };

export type ListBackupStorageLocationsQueryVariables = Exact<{ [key: string]: never; }>;


export type ListBackupStorageLocationsQuery = { __typename?: 'Query', backupStorageLocations: Array<{ __typename?: 'BackupStorageLocation', id: string, name: string, endpoint: string, bucket: string, region: string, createdOn: any, updatedOn?: any | null, environmentCount: number }> };

export type ListBackupsQueryVariables = Exact<{
  instanceId: Scalars['UUID']['input'];
}>;


export type ListBackupsQuery = { __typename?: 'Query', backups: Array<{ __typename?: 'Backup', id: string, name: string, status: string, createdOn: any, completedAt?: any | null, sizeBytes?: number | null, errorMessage?: string | null, ttl?: string | null, expiresAt?: any | null }> };

export type ListClustersQueryVariables = Exact<{ [key: string]: never; }>;


export type ListClustersQuery = { __typename?: 'Query', clusters: Array<{ __typename?: 'Cluster', id: string, name: string, config: Record<string, unknown> }> };

export type ListDriversQueryVariables = Exact<{ [key: string]: never; }>;


export type ListDriversQuery = { __typename?: 'Query', applicationDrivers: Array<{ __typename?: 'ApplicationDriver', id: string, name: string, versions: Array<{ __typename?: 'ApplicationDriverVersion', id: string, version: string, supportedVersions: string, sourceType: string, sourceRepository: string, sourceBranch?: string | null, sourcePath?: string | null, sourceCommitSha?: string | null, contentHash?: string | null, createdOn: any }> }> };

export type ListEnvironmentBackupsQueryVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
}>;


export type ListEnvironmentBackupsQuery = { __typename?: 'Query', environmentBackups: Array<{ __typename?: 'EnvironmentBackup', id: string, name: string, status: EnvironmentBackupStatus, createdOn: any, constituents: Array<{ __typename?: 'EnvironmentBackupConstituent', deploymentId: string, deploymentName: string, error?: string | null, backup?: { __typename?: 'Backup', id: string, name: string, status: string, completedAt?: any | null, sizeBytes?: number | null, errorMessage?: string | null } | null }> }> };

export type ListEnvironmentClonesQueryVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
}>;


export type ListEnvironmentClonesQuery = { __typename?: 'Query', environmentClones: Array<{ __typename?: 'EnvironmentClone', id: string, name: string, status: EnvironmentCloneStatus, sourceEnvironmentName: string, createdOn: any, updatedOn?: any | null, cloneErrors: Array<string>, createdEnvironment?: { __typename?: 'Environment', id: string, name: string } | null, environmentBackup?: { __typename?: 'EnvironmentBackup', id: string, name: string, status: EnvironmentBackupStatus } | null, deploymentResults: Array<{ __typename?: 'EnvironmentCloneDeploymentResult', deploymentId: string, deploymentName: string, outcome: EnvironmentCloneDeploymentOutcome, reason?: string | null }> }> };

export type ListEnvironmentRestoresQueryVariables = Exact<{
  environmentBackupId: Scalars['UUID']['input'];
}>;


export type ListEnvironmentRestoresQuery = { __typename?: 'Query', environmentRestores: Array<{ __typename?: 'EnvironmentRestore', id: string, status: EnvironmentRestoreStatus, createdOn: any, environmentBackupId: string, restores: Array<{ __typename?: 'Restore', id: string, name: string, status: string, targetInstanceId?: string | null, errorMessage?: string | null }>, skippedConstituents: Array<{ __typename?: 'SkippedConstituent', deploymentId: string, deploymentName: string, reason: string }> }> };

export type ListEnvironmentsQueryVariables = Exact<{
  includeDeleted?: InputMaybe<Scalars['Boolean']['input']>;
}>;


export type ListEnvironmentsQuery = { __typename?: 'Query', environments: Array<{ __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string }, deployments: Array<{ __typename?: 'Deployment', id: string, name: string, status: string, deletedAt?: any | null, internal: boolean, applicationVersion: string, components: Array<{ __typename?: 'Component', id: string, name: string, enabled: boolean }> }> }> };

export type ListGroupsQueryVariables = Exact<{
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type ListGroupsQuery = { __typename?: 'Query', groups: Array<{ __typename?: 'Group', id: string, name: string, role: Role }> };

export type ListRestoresQueryVariables = Exact<{
  backupId: Scalars['UUID']['input'];
  status?: InputMaybe<RestoreStatus>;
}>;


export type ListRestoresQuery = { __typename?: 'Query', restores: Array<{ __typename?: 'Restore', id: string, name: string, status: string, createdOn: any, startedAt?: any | null, completedAt?: any | null, targetNamespace: string, errorMessage?: string | null, componentStatuses?: Array<{ __typename?: 'ComponentRestoreStatus', componentName: string, status: string, errorMessage?: string | null }> | null }> };

export type ListUsersQueryVariables = Exact<{
  active?: InputMaybe<Scalars['Boolean']['input']>;
  role?: InputMaybe<Role>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type ListUsersQuery = { __typename?: 'Query', users: Array<{ __typename?: 'User', id: string, username: string, displayName: string, role: Role, effectiveRole: Role, active: boolean, createdOn?: any | null, updatedOn?: any | null, groups: Array<{ __typename?: 'Group', id: string, name: string, role: Role }> }> };

export type LoadLocalDriverMutationVariables = Exact<{
  path: Scalars['String']['input'];
}>;


export type LoadLocalDriverMutation = { __typename?: 'Mutation', loadLocalApplicationDriverVersion?: { __typename?: 'ApplicationDriverVersion', id: string, version: string, contentHash?: string | null, sourceCommitSha?: string | null, applicationDriverId: string } | null };

export type LoadRemoteDriverMutationVariables = Exact<{
  repositoryUrl: Scalars['String']['input'];
  branch: Scalars['String']['input'];
}>;


export type LoadRemoteDriverMutation = { __typename?: 'Mutation', loadRemoteApplicationDriverVersion?: { __typename?: 'ApplicationDriverVersion', id: string, version: string, contentHash?: string | null, sourceCommitSha?: string | null, applicationDriverId: string } | null };

export type LoginMutationVariables = Exact<{
  username: Scalars['String']['input'];
  password: Scalars['String']['input'];
}>;


export type LoginMutation = { __typename?: 'Mutation', login: { __typename?: 'LoginResult', token: string, user: { __typename?: 'User', id: string, username: string, displayName: string, role: Role, effectiveRole: Role, active: boolean } } };

export type LogoutMutationVariables = Exact<{ [key: string]: never; }>;


export type LogoutMutation = { __typename?: 'Mutation', logout: boolean };

export type ResetUserPasswordMutationVariables = Exact<{
  userId: Scalars['UUID']['input'];
  newPassword: Scalars['String']['input'];
}>;


export type ResetUserPasswordMutation = { __typename?: 'Mutation', resetUserPassword: boolean };

export type RestoreEnvironmentBackupMutationVariables = Exact<{
  environmentBackupId: Scalars['UUID']['input'];
}>;


export type RestoreEnvironmentBackupMutation = { __typename?: 'Mutation', restoreEnvironmentBackup: { __typename?: 'EnvironmentRestore', id: string, status: EnvironmentRestoreStatus, createdOn: any } };

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

export type UpdateDeploymentMutationVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
  input: UpdateDeploymentInput;
}>;


export type UpdateDeploymentMutation = { __typename?: 'Mutation', updateDeployment?: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, deploymentId?: string | null } | null };

export type UpdateDeploymentVersionMutationVariables = Exact<{
  deploymentId: Scalars['UUID']['input'];
  version: Scalars['String']['input'];
  parameters?: InputMaybe<Scalars['JSON']['input']>;
  driverVersionId?: InputMaybe<Scalars['UUID']['input']>;
}>;


export type UpdateDeploymentVersionMutation = { __typename?: 'Mutation', updateDeploymentVersion?: { __typename?: 'Task', id: string, type: string, status: string, message?: string | null, deploymentId?: string | null } | null };

export type UpdateEnvironmentMutationVariables = Exact<{
  environmentId: Scalars['UUID']['input'];
  input: UpdateEnvironmentInput;
}>;


export type UpdateEnvironmentMutation = { __typename?: 'Mutation', updateEnvironment?: { __typename?: 'Environment', id: string, name: string, config: Record<string, unknown>, cluster: { __typename?: 'Cluster', id: string, name: string } } | null };

export type UpdateGroupMutationVariables = Exact<{
  id: Scalars['UUID']['input'];
  input: UpdateGroupInput;
}>;


export type UpdateGroupMutation = { __typename?: 'Mutation', updateGroup: { __typename?: 'Group', id: string, name: string, role: Role } };

export type UpdateUserMutationVariables = Exact<{
  id: Scalars['UUID']['input'];
  input: UpdateUserInput;
}>;


export type UpdateUserMutation = { __typename?: 'Mutation', updateUser: { __typename?: 'User', id: string, username: string, displayName: string, role: Role, effectiveRole: Role, active: boolean, createdOn?: any | null, updatedOn?: any | null, groups: Array<{ __typename?: 'Group', id: string, name: string, role: Role }> } };



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

export const ChangePasswordDocument = `
    mutation ChangePassword($currentPassword: String!, $newPassword: String!) {
  changePassword(currentPassword: $currentPassword, newPassword: $newPassword)
}
    `;

export const useChangePasswordMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<ChangePasswordMutation, TError, ChangePasswordMutationVariables, TContext>) => {
    
    return useMutation<ChangePasswordMutation, TError, ChangePasswordMutationVariables, TContext>(
      {
    mutationKey: ['ChangePassword'],
    mutationFn: (variables?: ChangePasswordMutationVariables) => graphqlFetcher<ChangePasswordMutation, ChangePasswordMutationVariables>(ChangePasswordDocument, variables)(),
    ...options
  }
    )};

export const CloneEnvironmentDocument = `
    mutation CloneEnvironment($name: String!, $environmentId: UUID, $deploymentIds: [UUID!], $configOverride: UpdateEnvironmentInput, $clearConfigFields: [String!]) {
  cloneEnvironment(
    name: $name
    environmentId: $environmentId
    deploymentIds: $deploymentIds
    configOverride: $configOverride
    clearConfigFields: $clearConfigFields
  ) {
    id
    name
    status
    createdOn
  }
}
    `;

export const useCloneEnvironmentMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CloneEnvironmentMutation, TError, CloneEnvironmentMutationVariables, TContext>) => {
    
    return useMutation<CloneEnvironmentMutation, TError, CloneEnvironmentMutationVariables, TContext>(
      {
    mutationKey: ['CloneEnvironment'],
    mutationFn: (variables?: CloneEnvironmentMutationVariables) => graphqlFetcher<CloneEnvironmentMutation, CloneEnvironmentMutationVariables>(CloneEnvironmentDocument, variables)(),
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

export const CreateEnvironmentBackupDocument = `
    mutation CreateEnvironmentBackup($environmentId: UUID!, $name: String) {
  createEnvironmentBackup(environmentId: $environmentId, name: $name) {
    id
    name
    status
    createdOn
  }
}
    `;

export const useCreateEnvironmentBackupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateEnvironmentBackupMutation, TError, CreateEnvironmentBackupMutationVariables, TContext>) => {
    
    return useMutation<CreateEnvironmentBackupMutation, TError, CreateEnvironmentBackupMutationVariables, TContext>(
      {
    mutationKey: ['CreateEnvironmentBackup'],
    mutationFn: (variables?: CreateEnvironmentBackupMutationVariables) => graphqlFetcher<CreateEnvironmentBackupMutation, CreateEnvironmentBackupMutationVariables>(CreateEnvironmentBackupDocument, variables)(),
    ...options
  }
    )};

export const CreateGroupDocument = `
    mutation CreateGroup($input: CreateGroupInput!) {
  createGroup(input: $input) {
    id
    name
    role
  }
}
    `;

export const useCreateGroupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateGroupMutation, TError, CreateGroupMutationVariables, TContext>) => {
    
    return useMutation<CreateGroupMutation, TError, CreateGroupMutationVariables, TContext>(
      {
    mutationKey: ['CreateGroup'],
    mutationFn: (variables?: CreateGroupMutationVariables) => graphqlFetcher<CreateGroupMutation, CreateGroupMutationVariables>(CreateGroupDocument, variables)(),
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

export const CreateUserDocument = `
    mutation CreateUser($input: CreateUserInput!) {
  createUser(input: $input) {
    id
    username
    displayName
    role
    effectiveRole
    active
    groups {
      id
      name
      role
    }
    createdOn
    updatedOn
  }
}
    `;

export const useCreateUserMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<CreateUserMutation, TError, CreateUserMutationVariables, TContext>) => {
    
    return useMutation<CreateUserMutation, TError, CreateUserMutationVariables, TContext>(
      {
    mutationKey: ['CreateUser'],
    mutationFn: (variables?: CreateUserMutationVariables) => graphqlFetcher<CreateUserMutation, CreateUserMutationVariables>(CreateUserDocument, variables)(),
    ...options
  }
    )};

export const CurrentUserDocument = `
    query CurrentUser {
  currentUser {
    id
    username
    displayName
    role
    effectiveRole
    active
  }
}
    `;

export const useCurrentUserQuery = <
      TData = CurrentUserQuery,
      TError = Error
    >(
      variables?: CurrentUserQueryVariables,
      options?: Omit<UseQueryOptions<CurrentUserQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<CurrentUserQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<CurrentUserQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['CurrentUser'] : ['CurrentUser', variables],
    queryFn: graphqlFetcher<CurrentUserQuery, CurrentUserQueryVariables>(CurrentUserDocument, variables),
    ...options
  }
    )};

useCurrentUserQuery.getKey = (variables?: CurrentUserQueryVariables) => variables === undefined ? ['CurrentUser'] : ['CurrentUser', variables];

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

export const DeleteDeploymentDocument = `
    mutation DeleteDeployment($deploymentId: UUID!) {
  deleteDeployment(deploymentId: $deploymentId) {
    id
    type
    status
    deploymentId
  }
}
    `;

export const useDeleteDeploymentMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<DeleteDeploymentMutation, TError, DeleteDeploymentMutationVariables, TContext>) => {
    
    return useMutation<DeleteDeploymentMutation, TError, DeleteDeploymentMutationVariables, TContext>(
      {
    mutationKey: ['DeleteDeployment'],
    mutationFn: (variables?: DeleteDeploymentMutationVariables) => graphqlFetcher<DeleteDeploymentMutation, DeleteDeploymentMutationVariables>(DeleteDeploymentDocument, variables)(),
    ...options
  }
    )};

export const DeleteEnvironmentBackupDocument = `
    mutation DeleteEnvironmentBackup($environmentBackupId: UUID!) {
  deleteEnvironmentBackup(environmentBackupId: $environmentBackupId)
}
    `;

export const useDeleteEnvironmentBackupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<DeleteEnvironmentBackupMutation, TError, DeleteEnvironmentBackupMutationVariables, TContext>) => {
    
    return useMutation<DeleteEnvironmentBackupMutation, TError, DeleteEnvironmentBackupMutationVariables, TContext>(
      {
    mutationKey: ['DeleteEnvironmentBackup'],
    mutationFn: (variables?: DeleteEnvironmentBackupMutationVariables) => graphqlFetcher<DeleteEnvironmentBackupMutation, DeleteEnvironmentBackupMutationVariables>(DeleteEnvironmentBackupDocument, variables)(),
    ...options
  }
    )};

export const DeleteGroupDocument = `
    mutation DeleteGroup($id: UUID!) {
  deleteGroup(id: $id)
}
    `;

export const useDeleteGroupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<DeleteGroupMutation, TError, DeleteGroupMutationVariables, TContext>) => {
    
    return useMutation<DeleteGroupMutation, TError, DeleteGroupMutationVariables, TContext>(
      {
    mutationKey: ['DeleteGroup'],
    mutationFn: (variables?: DeleteGroupMutationVariables) => graphqlFetcher<DeleteGroupMutation, DeleteGroupMutationVariables>(DeleteGroupDocument, variables)(),
    ...options
  }
    )};

export const DeleteUserDocument = `
    mutation DeleteUser($id: UUID!) {
  deleteUser(id: $id)
}
    `;

export const useDeleteUserMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<DeleteUserMutation, TError, DeleteUserMutationVariables, TContext>) => {
    
    return useMutation<DeleteUserMutation, TError, DeleteUserMutationVariables, TContext>(
      {
    mutationKey: ['DeleteUser'],
    mutationFn: (variables?: DeleteUserMutationVariables) => graphqlFetcher<DeleteUserMutation, DeleteUserMutationVariables>(DeleteUserDocument, variables)(),
    ...options
  }
    )};

export const DeployDocument = `
    mutation Deploy($version: String, $driver: String!, $name: String, $environmentId: UUID!, $config: DeploymentConfigInput, $parameters: [ParameterValueInput!], $serviceNameOverrides: [ServiceNameOverride!]) {
  deploy(
    version: $version
    driver: $driver
    name: $name
    environmentId: $environmentId
    config: $config
    parameters: $parameters
    serviceNameOverrides: $serviceNameOverrides
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
    deletedAt
    config
    parameters
    applicationVersion
    applicationDriverVersionId
    applicationDriverVersion {
      id
      version
      contentHash
      sourceCommitSha
      applicationDriver {
        id
        name
      }
      parameters {
        name
        label
        kind
        default
        values
      }
    }
    environmentId
    environment {
      id
      name
      config
      cluster {
        id
        name
        config
      }
    }
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
      container
    }
    componentImageOverrides {
      component
      reference
      resolvedReference
      isOrphaned
      isApplicable
    }
    deployedServices {
      id
      driverServiceName
      resolvedName
      kind
      port
      primaryFqdn
      humanReadableFqdn
      primaryUrl
      humanReadableUrl
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

export const GetDeploymentPodsDocument = `
    query GetDeploymentPods($deploymentId: UUID!) {
  podStatuses(deploymentId: $deploymentId) {
    id
    podName
    namespace
    phase
    ready
    restartCount
    nodeName
    componentName
    startedAt
    createdOn
    lastPolledAt
    containerStatuses
  }
}
    `;

export const useGetDeploymentPodsQuery = <
      TData = GetDeploymentPodsQuery,
      TError = Error
    >(
      variables: GetDeploymentPodsQueryVariables,
      options?: Omit<UseQueryOptions<GetDeploymentPodsQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetDeploymentPodsQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetDeploymentPodsQuery, TError, TData>(
      {
    queryKey: ['GetDeploymentPods', variables],
    queryFn: graphqlFetcher<GetDeploymentPodsQuery, GetDeploymentPodsQueryVariables>(GetDeploymentPodsDocument, variables),
    ...options
  }
    )};

useGetDeploymentPodsQuery.getKey = (variables: GetDeploymentPodsQueryVariables) => ['GetDeploymentPods', variables];

export const GetDeploymentResolvedSchedulingDocument = `
    query GetDeploymentResolvedScheduling($deploymentId: UUID!) {
  deployment(deploymentId: $deploymentId) {
    id
    name
    resolvedScheduling {
      componentName
      config
      provenance
    }
  }
}
    `;

export const useGetDeploymentResolvedSchedulingQuery = <
      TData = GetDeploymentResolvedSchedulingQuery,
      TError = Error
    >(
      variables: GetDeploymentResolvedSchedulingQueryVariables,
      options?: Omit<UseQueryOptions<GetDeploymentResolvedSchedulingQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetDeploymentResolvedSchedulingQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetDeploymentResolvedSchedulingQuery, TError, TData>(
      {
    queryKey: ['GetDeploymentResolvedScheduling', variables],
    queryFn: graphqlFetcher<GetDeploymentResolvedSchedulingQuery, GetDeploymentResolvedSchedulingQueryVariables>(GetDeploymentResolvedSchedulingDocument, variables),
    ...options
  }
    )};

useGetDeploymentResolvedSchedulingQuery.getKey = (variables: GetDeploymentResolvedSchedulingQueryVariables) => ['GetDeploymentResolvedScheduling', variables];

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
    createdOn
    versions {
      id
      version
      supportedVersions
      sourceType
      sourceRepository
      sourceBranch
      sourcePath
      sourceCommitSha
      contentHash
      components
      createdOn
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
        container
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
    query GetEnvironment($environmentId: UUID!, $includeDeleted: Boolean = false) {
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
    deployments(includeDeleted: $includeDeleted) {
      id
      name
      status
      deletedAt
      internal
      applicationVersion
      applicationDriverVersionId
      applicationDriverVersion {
        version
        contentHash
        sourceCommitSha
        applicationDriver {
          name
        }
      }
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

export const GetEnvironmentCloneDocument = `
    query GetEnvironmentClone($environmentCloneId: UUID!) {
  environmentClone(environmentCloneId: $environmentCloneId) {
    id
    name
    status
    sourceEnvironmentName
    createdOn
    updatedOn
    requestedDeploymentIds
    configOverride
    clearConfigFields
    cloneErrors
    sourceEnvironment {
      id
      name
    }
    environmentBackup {
      id
      name
      status
    }
    createdEnvironment {
      id
      name
    }
    deploymentResults {
      deploymentId
      deploymentName
      outcome
      reason
      counterpartDeploymentId
      restoreId
    }
  }
}
    `;

export const useGetEnvironmentCloneQuery = <
      TData = GetEnvironmentCloneQuery,
      TError = Error
    >(
      variables: GetEnvironmentCloneQueryVariables,
      options?: Omit<UseQueryOptions<GetEnvironmentCloneQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetEnvironmentCloneQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetEnvironmentCloneQuery, TError, TData>(
      {
    queryKey: ['GetEnvironmentClone', variables],
    queryFn: graphqlFetcher<GetEnvironmentCloneQuery, GetEnvironmentCloneQueryVariables>(GetEnvironmentCloneDocument, variables),
    ...options
  }
    )};

useGetEnvironmentCloneQuery.getKey = (variables: GetEnvironmentCloneQueryVariables) => ['GetEnvironmentClone', variables];

export const GetGroupDocument = `
    query GetGroup {
  groups {
    id
    name
    role
  }
}
    `;

export const useGetGroupQuery = <
      TData = GetGroupQuery,
      TError = Error
    >(
      variables?: GetGroupQueryVariables,
      options?: Omit<UseQueryOptions<GetGroupQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<GetGroupQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<GetGroupQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['GetGroup'] : ['GetGroup', variables],
    queryFn: graphqlFetcher<GetGroupQuery, GetGroupQueryVariables>(GetGroupDocument, variables),
    ...options
  }
    )};

useGetGroupQuery.getKey = (variables?: GetGroupQueryVariables) => variables === undefined ? ['GetGroup'] : ['GetGroup', variables];

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
      contentHash
      sourceCommitSha
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
    ttl
    expiresAt
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
      supportedVersions
      sourceType
      sourceRepository
      sourceBranch
      sourcePath
      sourceCommitSha
      contentHash
      createdOn
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

export const ListEnvironmentBackupsDocument = `
    query ListEnvironmentBackups($environmentId: UUID!) {
  environmentBackups(environmentId: $environmentId) {
    id
    name
    status
    createdOn
    constituents {
      deploymentId
      deploymentName
      error
      backup {
        id
        name
        status
        completedAt
        sizeBytes
        errorMessage
      }
    }
  }
}
    `;

export const useListEnvironmentBackupsQuery = <
      TData = ListEnvironmentBackupsQuery,
      TError = Error
    >(
      variables: ListEnvironmentBackupsQueryVariables,
      options?: Omit<UseQueryOptions<ListEnvironmentBackupsQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListEnvironmentBackupsQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListEnvironmentBackupsQuery, TError, TData>(
      {
    queryKey: ['ListEnvironmentBackups', variables],
    queryFn: graphqlFetcher<ListEnvironmentBackupsQuery, ListEnvironmentBackupsQueryVariables>(ListEnvironmentBackupsDocument, variables),
    ...options
  }
    )};

useListEnvironmentBackupsQuery.getKey = (variables: ListEnvironmentBackupsQueryVariables) => ['ListEnvironmentBackups', variables];

export const ListEnvironmentClonesDocument = `
    query ListEnvironmentClones($environmentId: UUID!) {
  environmentClones(environmentId: $environmentId) {
    id
    name
    status
    sourceEnvironmentName
    createdOn
    updatedOn
    cloneErrors
    createdEnvironment {
      id
      name
    }
    environmentBackup {
      id
      name
      status
    }
    deploymentResults {
      deploymentId
      deploymentName
      outcome
      reason
    }
  }
}
    `;

export const useListEnvironmentClonesQuery = <
      TData = ListEnvironmentClonesQuery,
      TError = Error
    >(
      variables: ListEnvironmentClonesQueryVariables,
      options?: Omit<UseQueryOptions<ListEnvironmentClonesQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListEnvironmentClonesQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListEnvironmentClonesQuery, TError, TData>(
      {
    queryKey: ['ListEnvironmentClones', variables],
    queryFn: graphqlFetcher<ListEnvironmentClonesQuery, ListEnvironmentClonesQueryVariables>(ListEnvironmentClonesDocument, variables),
    ...options
  }
    )};

useListEnvironmentClonesQuery.getKey = (variables: ListEnvironmentClonesQueryVariables) => ['ListEnvironmentClones', variables];

export const ListEnvironmentRestoresDocument = `
    query ListEnvironmentRestores($environmentBackupId: UUID!) {
  environmentRestores(environmentBackupId: $environmentBackupId) {
    id
    status
    createdOn
    environmentBackupId
    restores {
      id
      name
      status
      targetInstanceId
      errorMessage
    }
    skippedConstituents {
      deploymentId
      deploymentName
      reason
    }
  }
}
    `;

export const useListEnvironmentRestoresQuery = <
      TData = ListEnvironmentRestoresQuery,
      TError = Error
    >(
      variables: ListEnvironmentRestoresQueryVariables,
      options?: Omit<UseQueryOptions<ListEnvironmentRestoresQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListEnvironmentRestoresQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListEnvironmentRestoresQuery, TError, TData>(
      {
    queryKey: ['ListEnvironmentRestores', variables],
    queryFn: graphqlFetcher<ListEnvironmentRestoresQuery, ListEnvironmentRestoresQueryVariables>(ListEnvironmentRestoresDocument, variables),
    ...options
  }
    )};

useListEnvironmentRestoresQuery.getKey = (variables: ListEnvironmentRestoresQueryVariables) => ['ListEnvironmentRestores', variables];

export const ListEnvironmentsDocument = `
    query ListEnvironments($includeDeleted: Boolean = false) {
  environments {
    id
    name
    config
    cluster {
      id
      name
    }
    deployments(includeDeleted: $includeDeleted) {
      id
      name
      status
      deletedAt
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

export const ListGroupsDocument = `
    query ListGroups($search: String) {
  groups(search: $search) {
    id
    name
    role
  }
}
    `;

export const useListGroupsQuery = <
      TData = ListGroupsQuery,
      TError = Error
    >(
      variables?: ListGroupsQueryVariables,
      options?: Omit<UseQueryOptions<ListGroupsQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListGroupsQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListGroupsQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['ListGroups'] : ['ListGroups', variables],
    queryFn: graphqlFetcher<ListGroupsQuery, ListGroupsQueryVariables>(ListGroupsDocument, variables),
    ...options
  }
    )};

useListGroupsQuery.getKey = (variables?: ListGroupsQueryVariables) => variables === undefined ? ['ListGroups'] : ['ListGroups', variables];

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

export const ListUsersDocument = `
    query ListUsers($active: Boolean, $role: Role, $search: String) {
  users(active: $active, role: $role, search: $search) {
    id
    username
    displayName
    role
    effectiveRole
    active
    groups {
      id
      name
      role
    }
    createdOn
    updatedOn
  }
}
    `;

export const useListUsersQuery = <
      TData = ListUsersQuery,
      TError = Error
    >(
      variables?: ListUsersQueryVariables,
      options?: Omit<UseQueryOptions<ListUsersQuery, TError, TData>, 'queryKey'> & { queryKey?: UseQueryOptions<ListUsersQuery, TError, TData>['queryKey'] }
    ) => {
    
    return useQuery<ListUsersQuery, TError, TData>(
      {
    queryKey: variables === undefined ? ['ListUsers'] : ['ListUsers', variables],
    queryFn: graphqlFetcher<ListUsersQuery, ListUsersQueryVariables>(ListUsersDocument, variables),
    ...options
  }
    )};

useListUsersQuery.getKey = (variables?: ListUsersQueryVariables) => variables === undefined ? ['ListUsers'] : ['ListUsers', variables];

export const LoadLocalDriverDocument = `
    mutation LoadLocalDriver($path: String!) {
  loadLocalApplicationDriverVersion(path: $path) {
    id
    version
    contentHash
    sourceCommitSha
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
    contentHash
    sourceCommitSha
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

export const LoginDocument = `
    mutation Login($username: String!, $password: String!) {
  login(username: $username, password: $password) {
    token
    user {
      id
      username
      displayName
      role
      effectiveRole
      active
    }
  }
}
    `;

export const useLoginMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<LoginMutation, TError, LoginMutationVariables, TContext>) => {
    
    return useMutation<LoginMutation, TError, LoginMutationVariables, TContext>(
      {
    mutationKey: ['Login'],
    mutationFn: (variables?: LoginMutationVariables) => graphqlFetcher<LoginMutation, LoginMutationVariables>(LoginDocument, variables)(),
    ...options
  }
    )};

export const LogoutDocument = `
    mutation Logout {
  logout
}
    `;

export const useLogoutMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<LogoutMutation, TError, LogoutMutationVariables, TContext>) => {
    
    return useMutation<LogoutMutation, TError, LogoutMutationVariables, TContext>(
      {
    mutationKey: ['Logout'],
    mutationFn: (variables?: LogoutMutationVariables) => graphqlFetcher<LogoutMutation, LogoutMutationVariables>(LogoutDocument, variables)(),
    ...options
  }
    )};

export const ResetUserPasswordDocument = `
    mutation ResetUserPassword($userId: UUID!, $newPassword: String!) {
  resetUserPassword(userId: $userId, newPassword: $newPassword)
}
    `;

export const useResetUserPasswordMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<ResetUserPasswordMutation, TError, ResetUserPasswordMutationVariables, TContext>) => {
    
    return useMutation<ResetUserPasswordMutation, TError, ResetUserPasswordMutationVariables, TContext>(
      {
    mutationKey: ['ResetUserPassword'],
    mutationFn: (variables?: ResetUserPasswordMutationVariables) => graphqlFetcher<ResetUserPasswordMutation, ResetUserPasswordMutationVariables>(ResetUserPasswordDocument, variables)(),
    ...options
  }
    )};

export const RestoreEnvironmentBackupDocument = `
    mutation RestoreEnvironmentBackup($environmentBackupId: UUID!) {
  restoreEnvironmentBackup(environmentBackupId: $environmentBackupId) {
    id
    status
    createdOn
  }
}
    `;

export const useRestoreEnvironmentBackupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<RestoreEnvironmentBackupMutation, TError, RestoreEnvironmentBackupMutationVariables, TContext>) => {
    
    return useMutation<RestoreEnvironmentBackupMutation, TError, RestoreEnvironmentBackupMutationVariables, TContext>(
      {
    mutationKey: ['RestoreEnvironmentBackup'],
    mutationFn: (variables?: RestoreEnvironmentBackupMutationVariables) => graphqlFetcher<RestoreEnvironmentBackupMutation, RestoreEnvironmentBackupMutationVariables>(RestoreEnvironmentBackupDocument, variables)(),
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

export const UpdateDeploymentDocument = `
    mutation UpdateDeployment($deploymentId: UUID!, $input: UpdateDeploymentInput!) {
  updateDeployment(deploymentId: $deploymentId, input: $input) {
    id
    type
    status
    message
    deploymentId
  }
}
    `;

export const useUpdateDeploymentMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<UpdateDeploymentMutation, TError, UpdateDeploymentMutationVariables, TContext>) => {
    
    return useMutation<UpdateDeploymentMutation, TError, UpdateDeploymentMutationVariables, TContext>(
      {
    mutationKey: ['UpdateDeployment'],
    mutationFn: (variables?: UpdateDeploymentMutationVariables) => graphqlFetcher<UpdateDeploymentMutation, UpdateDeploymentMutationVariables>(UpdateDeploymentDocument, variables)(),
    ...options
  }
    )};

export const UpdateDeploymentVersionDocument = `
    mutation UpdateDeploymentVersion($deploymentId: UUID!, $version: String!, $parameters: JSON, $driverVersionId: UUID) {
  updateDeploymentVersion(
    deploymentId: $deploymentId
    version: $version
    parameters: $parameters
    driverVersionId: $driverVersionId
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

export const UpdateEnvironmentDocument = `
    mutation UpdateEnvironment($environmentId: UUID!, $input: UpdateEnvironmentInput!) {
  updateEnvironment(environmentId: $environmentId, input: $input) {
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

export const useUpdateEnvironmentMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<UpdateEnvironmentMutation, TError, UpdateEnvironmentMutationVariables, TContext>) => {
    
    return useMutation<UpdateEnvironmentMutation, TError, UpdateEnvironmentMutationVariables, TContext>(
      {
    mutationKey: ['UpdateEnvironment'],
    mutationFn: (variables?: UpdateEnvironmentMutationVariables) => graphqlFetcher<UpdateEnvironmentMutation, UpdateEnvironmentMutationVariables>(UpdateEnvironmentDocument, variables)(),
    ...options
  }
    )};

export const UpdateGroupDocument = `
    mutation UpdateGroup($id: UUID!, $input: UpdateGroupInput!) {
  updateGroup(id: $id, input: $input) {
    id
    name
    role
  }
}
    `;

export const useUpdateGroupMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<UpdateGroupMutation, TError, UpdateGroupMutationVariables, TContext>) => {
    
    return useMutation<UpdateGroupMutation, TError, UpdateGroupMutationVariables, TContext>(
      {
    mutationKey: ['UpdateGroup'],
    mutationFn: (variables?: UpdateGroupMutationVariables) => graphqlFetcher<UpdateGroupMutation, UpdateGroupMutationVariables>(UpdateGroupDocument, variables)(),
    ...options
  }
    )};

export const UpdateUserDocument = `
    mutation UpdateUser($id: UUID!, $input: UpdateUserInput!) {
  updateUser(id: $id, input: $input) {
    id
    username
    displayName
    role
    effectiveRole
    active
    groups {
      id
      name
      role
    }
    createdOn
    updatedOn
  }
}
    `;

export const useUpdateUserMutation = <
      TError = Error,
      TContext = unknown
    >(options?: UseMutationOptions<UpdateUserMutation, TError, UpdateUserMutationVariables, TContext>) => {
    
    return useMutation<UpdateUserMutation, TError, UpdateUserMutationVariables, TContext>(
      {
    mutationKey: ['UpdateUser'],
    mutationFn: (variables?: UpdateUserMutationVariables) => graphqlFetcher<UpdateUserMutation, UpdateUserMutationVariables>(UpdateUserDocument, variables)(),
    ...options
  }
    )};
