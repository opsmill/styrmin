/* eslint-disable @typescript-eslint/no-explicit-any */
import { z } from "zod";

import type {
  AffinityBlockInput,
  AffinityTermInput,
  LabelSelectorInput,
  PostRenderInjectionInput,
  SchedulingInput,
  TolerationEffect,
  TolerationInput,
  TolerationOperator,
  TopologySpreadConstraintInput,
  WhenUnsatisfiable,
} from "@/generated/graphql";

// ---------------------------------------------------------------------------
// Zod — per-block schemas composed into `schedulingSchema`.
//
// Validation rules come from data-model.md (Scheduling row):
//   - CPU/memory: Kubernetes quantity regex
//   - tolerations: key required when operator === EQUAL
//   - topology spread: maxSkew >= 1
//   - runtime class: Kubernetes RFC1035 name regex
// ---------------------------------------------------------------------------

const K8S_QUANTITY = /^\d+(\.\d+)?(m|Mi|Gi|Ki|Ti|Pi|Ei|k|M|G|T|P|E)?$/;
const K8S_NAME = /^[a-z]([-a-z0-9]*[a-z0-9])?$/;

const quantityField = z
  .string()
  .trim()
  .min(0)
  .refine((v: any) => v === "" || K8S_QUANTITY.test(v), {
    message: "Must be a Kubernetes quantity (e.g. 250m, 1, 256Mi, 2Gi)",
  });

const tolerationOperatorEnum = z.enum([
  "EQUAL",
  "EXISTS",
]) satisfies z.ZodType<TolerationOperator>;
const tolerationEffectEnum = z.enum([
  "NO_SCHEDULE",
  "PREFER_NO_SCHEDULE",
  "NO_EXECUTE",
]) satisfies z.ZodType<TolerationEffect>;
const whenUnsatisfiableEnum = z.enum([
  "DO_NOT_SCHEDULE",
  "SCHEDULE_ANYWAY",
]) satisfies z.ZodType<WhenUnsatisfiable>;

const tolerationSchema = z
  .object({
    key: z.string().optional(),
    operator: tolerationOperatorEnum.optional(),
    value: z.string().optional(),
    effect: tolerationEffectEnum.optional(),
    tolerationSeconds: z.number().int().nonnegative().optional(),
  })
  .refine(
    (t: any) =>
      t.operator !== "EQUAL" || (t.key !== undefined && t.key.trim() !== ""),
    { message: "key is required when operator is EQUAL", path: ["key"] },
  );

const labelSelectorSchema: z.ZodType<LabelSelectorInput> = z.object({
  matchLabels: z.record(z.string(), z.string()).optional(),
  matchExpressions: z
    .array(
      z.object({
        key: z.string().min(1),
        operator: z.enum(["IN", "NOT_IN", "EXISTS", "DOES_NOT_EXIST"]),
        values: z.array(z.string()).optional(),
      }),
    )
    .optional(),
});

const topologySpreadSchema: z.ZodType<TopologySpreadConstraintInput> = z.object(
  {
    maxSkew: z.number().int().min(1, "maxSkew must be >= 1"),
    topologyKey: z.string().min(1, "topologyKey is required"),
    whenUnsatisfiable: whenUnsatisfiableEnum,
    labelSelector: labelSelectorSchema.optional(),
    minDomains: z.number().int().min(1).optional(),
    matchLabelKeys: z.array(z.string()).optional(),
    nodeAffinityPolicy: z.string().optional(),
    nodeTaintsPolicy: z.string().optional(),
  },
);

const affinityTermSchema: z.ZodType<AffinityTermInput> = z.object({
  topologyKey: z.string(),
  labelSelector: labelSelectorSchema.optional(),
  deploymentRef: z
    .object({
      deploymentId: z.string().optional(),
      deploymentName: z.string().optional(),
      components: z.array(z.string()).optional(),
    })
    .optional(),
  matchLabelKeys: z.array(z.string()).optional(),
  mismatchLabelKeys: z.array(z.string()).optional(),
  namespaceSelector: labelSelectorSchema.optional(),
  namespaces: z.array(z.string()).optional(),
});

const affinityBlockSchema: z.ZodType<AffinityBlockInput> = z.object({
  required: z.array(affinityTermSchema).optional(),
  preferred: z
    .array(
      z.object({
        weight: z.number().int().min(1).max(100),
        term: affinityTermSchema,
      }),
    )
    .optional(),
  replace: z.boolean().optional(),
});

export const schedulingSchema: z.ZodType<SchedulingInput> = z.object({
  resources: z
    .object({
      requests: z
        .object({
          cpu: quantityField.optional(),
          memory: quantityField.optional(),
          ephemeralStorage: quantityField.optional(),
        })
        .optional(),
      limits: z
        .object({
          cpu: quantityField.optional(),
          memory: quantityField.optional(),
          ephemeralStorage: quantityField.optional(),
        })
        .optional(),
    })
    .optional(),
  tolerations: z.array(tolerationSchema).optional(),
  topologySpreadConstraints: z.array(topologySpreadSchema).optional(),
  nodeAffinity: affinityBlockSchema.optional(),
  podAffinity: affinityBlockSchema.optional(),
  podAntiAffinity: affinityBlockSchema.optional(),
  runtimeClass: z
    .string()
    .trim()
    .optional()
    .refine((v: any) => !v || K8S_NAME.test(v), {
      message: "Must be a valid Kubernetes name (RFC 1035)",
    }),
  inject: z
    .object({
      nodeAffinity: z.boolean().optional(),
      podAffinity: z.boolean().optional(),
      resources: z.boolean().optional(),
      runtimeClass: z.boolean().optional(),
      tolerations: z.boolean().optional(),
      topologySpread: z.boolean().optional(),
    })
    .optional(),
});

// ---------------------------------------------------------------------------
// Constants surfaced as Select dropdown options.
// ---------------------------------------------------------------------------

export const TOLERATION_OPERATORS: TolerationOperator[] = ["EQUAL", "EXISTS"];
export const TOLERATION_EFFECTS: TolerationEffect[] = [
  "NO_SCHEDULE",
  "PREFER_NO_SCHEDULE",
  "NO_EXECUTE",
];
export const WHEN_UNSATISFIABLE: WhenUnsatisfiable[] = [
  "DO_NOT_SCHEDULE",
  "SCHEDULE_ANYWAY",
];

export const INJECTION_LABELS: Record<keyof PostRenderInjectionInput, string> =
  {
    nodeAffinity: "Inject node affinity",
    podAffinity: "Inject pod affinity",
    resources: "Inject resources",
    runtimeClass: "Inject runtime class",
    tolerations: "Inject tolerations",
    topologySpread: "Inject topology spread",
  };

// ---------------------------------------------------------------------------
// Empty-row factories. Each builds a new sub-tree the Add buttons push into
// their respective field arrays.
// ---------------------------------------------------------------------------

export function emptyToleration(): TolerationInput {
  return { operator: "EQUAL", effect: "NO_SCHEDULE" };
}

export function emptyTopologySpread(): TopologySpreadConstraintInput {
  return {
    maxSkew: 1,
    topologyKey: "kubernetes.io/hostname",
    whenUnsatisfiable: "SCHEDULE_ANYWAY",
  };
}

export function emptyAffinityTerm(topologyKey: string): AffinityTermInput {
  return { topologyKey, labelSelector: {} };
}

export type AffinityKind = "nodeAffinity" | "podAffinity" | "podAntiAffinity";
