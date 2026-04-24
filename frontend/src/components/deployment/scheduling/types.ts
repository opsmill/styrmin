export type TolerationOperator = "Equal" | "Exists";
export type TolerationEffect = "NoSchedule" | "PreferNoSchedule" | "NoExecute";

export interface Toleration {
  key?: string;
  operator?: TolerationOperator;
  value?: string;
  effect?: TolerationEffect;
  toleration_seconds?: number;
}

export interface ResourceSpec {
  cpu?: string;
  memory?: string;
  ephemeral_storage?: string;
  extended?: Record<string, string>;
}

export interface ResourceRequirements {
  requests?: ResourceSpec;
  limits?: ResourceSpec;
}

export type LabelSelectorOperator = "In" | "NotIn" | "Exists" | "DoesNotExist";

export interface LabelSelectorRequirement {
  key: string;
  operator: LabelSelectorOperator;
  values?: string[];
}

export interface LabelSelector {
  match_labels?: Record<string, string>;
  match_expressions?: LabelSelectorRequirement[];
}

export interface DeploymentReference {
  deployment_id?: string;
  deployment_name?: string;
  components?: string[];
}

export interface AffinityTerm {
  topology_key: string;
  label_selector?: LabelSelector;
  deployment_ref?: DeploymentReference;
}

export interface WeightedAffinityTerm {
  weight: number;
  term: AffinityTerm;
}

export interface AffinityBlock {
  required?: AffinityTerm[];
  preferred?: WeightedAffinityTerm[];
  replace?: boolean;
}

export type WhenUnsatisfiable = "DoNotSchedule" | "ScheduleAnyway";

export interface TopologySpreadConstraint {
  max_skew: number;
  topology_key: string;
  when_unsatisfiable: WhenUnsatisfiable;
  label_selector?: LabelSelector;
}

export interface SchedulingConfig {
  tolerations?: Toleration[];
  resources?: ResourceRequirements;
  topology_spread_constraints?: TopologySpreadConstraint[];
  node_affinity?: AffinityBlock;
  pod_affinity?: AffinityBlock;
  pod_anti_affinity?: AffinityBlock;
  runtime_class?: string;
}

export const TOLERATION_OPERATORS: TolerationOperator[] = ["Equal", "Exists"];
export const TOLERATION_EFFECTS: TolerationEffect[] = [
  "NoSchedule",
  "PreferNoSchedule",
  "NoExecute",
];
export const LABEL_SELECTOR_OPERATORS: LabelSelectorOperator[] = [
  "In",
  "NotIn",
  "Exists",
  "DoesNotExist",
];
export const WHEN_UNSATISFIABLE: WhenUnsatisfiable[] = [
  "DoNotSchedule",
  "ScheduleAnyway",
];
