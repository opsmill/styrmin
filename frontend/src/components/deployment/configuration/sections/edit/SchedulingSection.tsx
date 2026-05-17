// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "@tanstack/react-form";
import { X } from "lucide-react";
import { z } from "zod";

import type { ReactFormLike } from "./types";

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
  UpdateDeploymentInput,
  WeightedAffinityTermInput,
  WhenUnsatisfiable,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { diff } from "@/lib/config-diff";
import type {
  DriverParameterSchema,
  SectionId,
} from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";

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

const tolerationOperator = z.enum([
  "EQUAL",
  "EXISTS",
]) satisfies z.ZodType<TolerationOperator>;
const tolerationEffect = z.enum([
  "NO_SCHEDULE",
  "PREFER_NO_SCHEDULE",
  "NO_EXECUTE",
]) satisfies z.ZodType<TolerationEffect>;
const whenUnsatisfiable = z.enum([
  "DO_NOT_SCHEDULE",
  "SCHEDULE_ANYWAY",
]) satisfies z.ZodType<WhenUnsatisfiable>;

const tolerationSchema = z
  .object({
    key: z.string().optional(),
    operator: tolerationOperator.optional(),
    value: z.string().optional(),
    effect: tolerationEffect.optional(),
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
    whenUnsatisfiable,
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
// Helpers — pure setters that produce a new SchedulingInput sub-tree.
// ---------------------------------------------------------------------------

const TOLERATION_OPERATORS: TolerationOperator[] = ["EQUAL", "EXISTS"];
const TOLERATION_EFFECTS: TolerationEffect[] = [
  "NO_SCHEDULE",
  "PREFER_NO_SCHEDULE",
  "NO_EXECUTE",
];
const WHEN_UNSATISFIABLE: WhenUnsatisfiable[] = [
  "DO_NOT_SCHEDULE",
  "SCHEDULE_ANYWAY",
];

const INJECTION_LABELS: Record<keyof PostRenderInjectionInput, string> = {
  nodeAffinity: "Inject node affinity",
  podAffinity: "Inject pod affinity",
  resources: "Inject resources",
  runtimeClass: "Inject runtime class",
  tolerations: "Inject tolerations",
  topologySpread: "Inject topology spread",
};

function emptyToleration(): TolerationInput {
  return { operator: "EQUAL", effect: "NO_SCHEDULE" };
}

function emptyTopologySpread(): TopologySpreadConstraintInput {
  return {
    maxSkew: 1,
    topologyKey: "kubernetes.io/hostname",
    whenUnsatisfiable: "SCHEDULE_ANYWAY",
  };
}

function emptyAffinityTerm(topologyKey: string): AffinityTermInput {
  return { topologyKey, labelSelector: {} };
}

// ---------------------------------------------------------------------------
// Section component
// ---------------------------------------------------------------------------

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
  anchorId: SectionId;
}

/**
 * Scheduling section of the edit drawer. Ports the legacy
 * `SchedulingConfigDialog` sub-blocks but binds them to the drawer's single
 * TanStack Form instance via `form.Field` at sub-paths under
 * `scheduling.*`.
 *
 * Sub-blocks (top-to-bottom):
 *   - Resources (request/limit for CPU + memory)
 *   - Tolerations (field array)
 *   - Topology spread (field array)
 *   - Node affinity (required/preferred lists)
 *   - Pod affinity, Pod anti-affinity (same shape, pod-label targets)
 *   - Runtime class
 *   - Post-render injection toggles (per `PostRenderInjectionInput`)
 *
 * Every leaf input is wrapped in `<ChangedFieldFrame>` so the amber outline
 * and "from X (env)" annotation render uniformly across the drawer.
 */
export function SchedulingSection({
  form,
  initial,
  environment,
  anchorId,
}: Props) {
  const initialScheduling = (initial.scheduling ?? {}) as SchedulingInput;
  const envScheduling = (environment.scheduling ?? {}) as SchedulingInput;

  const changedCount = useStore(
    form.store,
    (state: any) =>
      diff(initial, state.values, [] as DriverParameterSchema).entries.filter(
        (e: any) => e.section === anchorId,
      ).length,
  );

  return (
    <section
      data-section={anchorId}
      id={`${anchorId}-anchor`}
      className="scroll-mt-4"
    >
      <div className="mb-3 flex items-center gap-3">
        <h3
          id={`${anchorId}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-slate-700"
        >
          Scheduling
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900"
          >
            {changedCount} changed
          </span>
        )}
      </div>

      <div className="space-y-6">
        {/* ── Resources ───────────────────────────────────────────── */}
        <SubBlock
          title="Resources"
          description="Pod-container CPU and memory requests/limits."
          testid="scheduling-section-resources"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {(["requests", "limits"] as const).map((slot) => (
              <div key={slot} className="space-y-2 rounded-md border p-3">
                <Label className="font-medium capitalize">{slot}</Label>
                {(["cpu", "memory"] as const).map((field) => {
                  const name = `scheduling.resources.${slot}.${field}` as const;
                  return (
                    <form.Field key={name} name={name}>
                      {(f: any) => (
                        <ChangedFieldFrame
                          name={name}
                          form={form}
                          initial={initialScheduling.resources?.[slot]?.[field]}
                          environment={envScheduling.resources?.[slot]?.[field]}
                        >
                          <div className="space-y-1">
                            <Label
                              htmlFor={`sched-res-${slot}-${field}`}
                              className="text-xs uppercase tracking-wide"
                            >
                              {field}
                            </Label>
                            <Input
                              id={`sched-res-${slot}-${field}`}
                              data-testid={`sched-res-${slot}-${field}`}
                              value={f.state.value ?? ""}
                              onChange={(e: any) =>
                                f.handleChange(
                                  e.target.value === ""
                                    ? undefined
                                    : e.target.value,
                                )
                              }
                              onBlur={f.handleBlur}
                              placeholder={
                                field === "cpu"
                                  ? "e.g. 250m or 2"
                                  : "e.g. 256Mi or 1Gi"
                              }
                            />
                          </div>
                        </ChangedFieldFrame>
                      )}
                    </form.Field>
                  );
                })}
              </div>
            ))}
          </div>
        </SubBlock>

        {/* ── Tolerations ─────────────────────────────────────────── */}
        <SubBlock
          title="Tolerations"
          description="Allow pods to schedule onto tainted nodes."
          testid="scheduling-section-tolerations"
        >
          <form.Field name="scheduling.tolerations" mode="array">
            {(field: any) => {
              const rows = field.state.value ?? [];
              return (
                <div className="space-y-3">
                  {rows.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      No tolerations.
                    </p>
                  )}
                  {rows.map((_: any, index: any) => (
                    <TolerationRow
                      key={`tol-${index}`}
                      index={index}
                      form={form}
                      initialScheduling={initialScheduling}
                      envScheduling={envScheduling}
                      onRemove={() => field.removeValue(index)}
                    />
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="add-toleration"
                    onClick={() => field.pushValue(emptyToleration())}
                  >
                    Add toleration
                  </Button>
                </div>
              );
            }}
          </form.Field>
        </SubBlock>

        {/* ── Topology spread ─────────────────────────────────────── */}
        <SubBlock
          title="Topology spread"
          description="Distribute pods across failure domains."
          testid="scheduling-section-topology-spread"
        >
          <form.Field name="scheduling.topologySpreadConstraints" mode="array">
            {(field: any) => {
              const rows = field.state.value ?? [];
              return (
                <div className="space-y-3">
                  {rows.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      No topology spread constraints.
                    </p>
                  )}
                  {rows.map((_: any, index: any) => (
                    <TopologySpreadRow
                      key={`tsc-${index}`}
                      index={index}
                      form={form}
                      initialScheduling={initialScheduling}
                      envScheduling={envScheduling}
                      onRemove={() => field.removeValue(index)}
                    />
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="add-topology-spread"
                    onClick={() => field.pushValue(emptyTopologySpread())}
                  >
                    Add constraint
                  </Button>
                </div>
              );
            }}
          </form.Field>
        </SubBlock>

        {/* ── Node affinity ───────────────────────────────────────── */}
        <AffinityBlock
          kind="nodeAffinity"
          label="Node affinity"
          description="Schedule pods to nodes whose labels match."
          form={form}
          initialScheduling={initialScheduling}
          envScheduling={envScheduling}
        />

        {/* ── Pod affinity ────────────────────────────────────────── */}
        <AffinityBlock
          kind="podAffinity"
          label="Pod affinity"
          description="Co-locate pods with matching peers."
          form={form}
          initialScheduling={initialScheduling}
          envScheduling={envScheduling}
        />

        {/* ── Pod anti-affinity ───────────────────────────────────── */}
        <AffinityBlock
          kind="podAntiAffinity"
          label="Pod anti-affinity"
          description="Spread pods away from matching peers."
          form={form}
          initialScheduling={initialScheduling}
          envScheduling={envScheduling}
        />

        {/* ── Runtime class ───────────────────────────────────────── */}
        <SubBlock
          title="Runtime class"
          description="Kubernetes RuntimeClass applied to pods (e.g. kata-e2e)."
          testid="scheduling-section-runtime-class"
        >
          <form.Field name="scheduling.runtimeClass">
            {(f: any) => (
              <ChangedFieldFrame
                name="scheduling.runtimeClass"
                form={form}
                initial={initialScheduling.runtimeClass}
                environment={envScheduling.runtimeClass}
              >
                <div className="space-y-1">
                  <Label htmlFor="sched-runtime-class">
                    Runtime class name
                  </Label>
                  <Input
                    id="sched-runtime-class"
                    data-testid="sched-runtime-class"
                    value={f.state.value ?? ""}
                    onChange={(e: any) =>
                      f.handleChange(
                        e.target.value === "" ? undefined : e.target.value,
                      )
                    }
                    onBlur={f.handleBlur}
                    placeholder="e.g. kata-e2e"
                  />
                </div>
              </ChangedFieldFrame>
            )}
          </form.Field>
        </SubBlock>

        {/* ── Post-render injection toggles ───────────────────────── */}
        <SubBlock
          title="Post-render injection"
          description="Opt out of injecting individual scheduling blocks into rendered manifests."
          testid="scheduling-section-inject"
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(
              Object.keys(INJECTION_LABELS) as Array<
                keyof PostRenderInjectionInput
              >
            ).map((key) => {
              const name = `scheduling.inject.${key}` as const;
              return (
                <form.Field key={name} name={name}>
                  {(f: any) => (
                    <ChangedFieldFrame
                      name={name}
                      form={form}
                      initial={initialScheduling.inject?.[key]}
                      environment={envScheduling.inject?.[key]}
                    >
                      <label className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={f.state.value ?? false}
                          onCheckedChange={(checked: any) =>
                            f.handleChange(checked === true)
                          }
                          data-testid={`sched-inject-${key}`}
                        />
                        <span>{INJECTION_LABELS[key]}</span>
                      </label>
                    </ChangedFieldFrame>
                  )}
                </form.Field>
              );
            })}
          </div>
        </SubBlock>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Visual sub-block wrapper
// ---------------------------------------------------------------------------

function SubBlock({
  title,
  description,
  testid,
  children,
}: {
  title: string;
  description?: string;
  testid: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2" data-testid={testid}>
      <h4 className="text-sm font-semibold text-slate-800">{title}</h4>
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toleration row
// ---------------------------------------------------------------------------

function TolerationRow({
  index,
  form,
  initialScheduling,
  envScheduling,
  onRemove,
}: {
  index: number;
  form: ReactFormLike;
  initialScheduling: SchedulingInput;
  envScheduling: SchedulingInput;
  onRemove: () => void;
}) {
  const initialRow = initialScheduling.tolerations?.[index];
  const envRow = envScheduling.tolerations?.[index];
  const base = `scheduling.tolerations.${index}` as const;

  return (
    <div
      className="space-y-2 rounded-md border p-3"
      data-testid="toleration-row"
    >
      <div className="grid grid-cols-2 gap-2">
        <form.Field name={`${base}.key`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${base}.key`}
              form={form}
              initial={initialRow?.key}
              environment={envRow?.key}
            >
              <div className="space-y-1">
                <Label htmlFor={`tol-key-${index}`}>Key</Label>
                <Input
                  id={`tol-key-${index}`}
                  value={f.state.value ?? ""}
                  onChange={(e: any) =>
                    f.handleChange(
                      e.target.value === "" ? undefined : e.target.value,
                    )
                  }
                  placeholder="e.g. dedicated"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        <form.Field name={`${base}.operator`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${base}.operator`}
              form={form}
              initial={initialRow?.operator}
              environment={envRow?.operator}
            >
              <div className="space-y-1">
                <Label htmlFor={`tol-operator-${index}`}>Operator</Label>
                <Select
                  value={f.state.value ?? "EQUAL"}
                  onValueChange={(v: any) =>
                    f.handleChange(v as TolerationOperator)
                  }
                >
                  <SelectTrigger id={`tol-operator-${index}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TOLERATION_OPERATORS.map((op: any) => (
                      <SelectItem key={op} value={op}>
                        {op}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        <form.Field name={`${base}.value`}>
          {(f: any) => {
            const operator = form.getFieldValue(`${base}.operator`) as
              | TolerationOperator
              | undefined;
            return (
              <ChangedFieldFrame
                name={`${base}.value`}
                form={form}
                initial={initialRow?.value}
                environment={envRow?.value}
              >
                <div className="space-y-1">
                  <Label htmlFor={`tol-value-${index}`}>Value</Label>
                  <Input
                    id={`tol-value-${index}`}
                    value={f.state.value ?? ""}
                    onChange={(e: any) =>
                      f.handleChange(
                        e.target.value === "" ? undefined : e.target.value,
                      )
                    }
                    placeholder="e.g. batch"
                    disabled={operator === "EXISTS"}
                  />
                </div>
              </ChangedFieldFrame>
            );
          }}
        </form.Field>

        <form.Field name={`${base}.effect`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${base}.effect`}
              form={form}
              initial={initialRow?.effect}
              environment={envRow?.effect}
            >
              <div className="space-y-1">
                <Label htmlFor={`tol-effect-${index}`}>Effect</Label>
                <Select
                  value={f.state.value ?? "NO_SCHEDULE"}
                  onValueChange={(v: any) =>
                    f.handleChange(v as TolerationEffect)
                  }
                >
                  <SelectTrigger id={`tol-effect-${index}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TOLERATION_EFFECTS.map((ef: any) => (
                      <SelectItem key={ef} value={ef}>
                        {ef}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>
      </div>

      <div className="flex items-end justify-between gap-2">
        <form.Field name={`${base}.tolerationSeconds`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${base}.tolerationSeconds`}
              form={form}
              initial={initialRow?.tolerationSeconds}
              environment={envRow?.tolerationSeconds}
            >
              <div className="space-y-1">
                <Label htmlFor={`tol-seconds-${index}`}>
                  Toleration seconds (NO_EXECUTE)
                </Label>
                <Input
                  id={`tol-seconds-${index}`}
                  type="number"
                  min={0}
                  value={f.state.value ?? ""}
                  onChange={(e: any) =>
                    f.handleChange(
                      e.target.value === ""
                        ? undefined
                        : Number(e.target.value),
                    )
                  }
                  className="w-48"
                  placeholder="only for NO_EXECUTE"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Remove toleration ${index + 1}`}
          onClick={onRemove}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Topology spread row
// ---------------------------------------------------------------------------

function TopologySpreadRow({
  index,
  form,
  initialScheduling,
  envScheduling,
  onRemove,
}: {
  index: number;
  form: ReactFormLike;
  initialScheduling: SchedulingInput;
  envScheduling: SchedulingInput;
  onRemove: () => void;
}) {
  const initialRow = initialScheduling.topologySpreadConstraints?.[index];
  const envRow = envScheduling.topologySpreadConstraints?.[index];
  const base = `scheduling.topologySpreadConstraints.${index}` as const;

  return (
    <div
      className="space-y-3 rounded-md border p-3"
      data-testid="topology-spread-row"
    >
      <div className="grid grid-cols-3 gap-2">
        <form.Field name={`${base}.maxSkew`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${base}.maxSkew`}
              form={form}
              initial={initialRow?.maxSkew}
              environment={envRow?.maxSkew}
            >
              <div className="space-y-1">
                <Label htmlFor={`tsc-skew-${index}`}>Max skew</Label>
                <Input
                  id={`tsc-skew-${index}`}
                  type="number"
                  min={1}
                  value={f.state.value ?? 1}
                  onChange={(e: any) =>
                    f.handleChange(Number(e.target.value) || 1)
                  }
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        <form.Field name={`${base}.topologyKey`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${base}.topologyKey`}
              form={form}
              initial={initialRow?.topologyKey}
              environment={envRow?.topologyKey}
            >
              <div className="space-y-1">
                <Label htmlFor={`tsc-topology-${index}`}>Topology key</Label>
                <Input
                  id={`tsc-topology-${index}`}
                  value={f.state.value ?? ""}
                  onChange={(e: any) => f.handleChange(e.target.value)}
                  placeholder="kubernetes.io/hostname"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        <form.Field name={`${base}.whenUnsatisfiable`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${base}.whenUnsatisfiable`}
              form={form}
              initial={initialRow?.whenUnsatisfiable}
              environment={envRow?.whenUnsatisfiable}
            >
              <div className="space-y-1">
                <Label htmlFor={`tsc-when-${index}`}>When unsatisfiable</Label>
                <Select
                  value={f.state.value ?? "SCHEDULE_ANYWAY"}
                  onValueChange={(v: any) =>
                    f.handleChange(v as WhenUnsatisfiable)
                  }
                >
                  <SelectTrigger id={`tsc-when-${index}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WHEN_UNSATISFIABLE.map((w: any) => (
                      <SelectItem key={w} value={w}>
                        {w}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>
      </div>

      <form.Field name={`${base}.minDomains`}>
        {(f: any) => (
          <ChangedFieldFrame
            name={`${base}.minDomains`}
            form={form}
            initial={initialRow?.minDomains}
            environment={envRow?.minDomains}
          >
            <div className="space-y-1">
              <Label htmlFor={`tsc-mindomains-${index}`}>
                Min domains (optional)
              </Label>
              <Input
                id={`tsc-mindomains-${index}`}
                type="number"
                min={1}
                value={f.state.value ?? ""}
                onChange={(e: any) =>
                  f.handleChange(
                    e.target.value === "" ? undefined : Number(e.target.value),
                  )
                }
                className="w-48"
              />
            </div>
          </ChangedFieldFrame>
        )}
      </form.Field>

      <div className="flex justify-end">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Remove topology spread constraint ${index + 1}`}
          onClick={onRemove}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Affinity block (Node/Pod/Pod-Anti)
// ---------------------------------------------------------------------------

type AffinityKind = "nodeAffinity" | "podAffinity" | "podAntiAffinity";

function AffinityBlock({
  kind,
  label,
  description,
  form,
  initialScheduling,
  envScheduling,
}: {
  kind: AffinityKind;
  label: string;
  description: string;
  form: ReactFormLike;
  initialScheduling: SchedulingInput;
  envScheduling: SchedulingInput;
}) {
  const initialBlock = initialScheduling[kind] as
    | AffinityBlockInput
    | undefined;
  const envBlock = envScheduling[kind] as AffinityBlockInput | undefined;
  const defaultTopologyKey =
    kind === "nodeAffinity" ? "" : "kubernetes.io/hostname";

  return (
    <SubBlock
      title={label}
      description={description}
      testid={`scheduling-section-${kind}`}
    >
      <div className="space-y-4">
        {/* Required */}
        <form.Field name={`scheduling.${kind}.required`} mode="array">
          {(field: any) => {
            const rows = field.state.value ?? [];
            return (
              <div className="space-y-2">
                <Label className="font-medium">Required</Label>
                <p className="text-xs text-muted-foreground">
                  Hard constraint — pod is not scheduled unless satisfied.
                </p>
                {rows.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No required terms.
                  </p>
                )}
                {rows.map((_: any, index: any) => (
                  <AffinityTermEditor
                    key={`${kind}-req-${index}`}
                    form={form}
                    pathBase={`scheduling.${kind}.required.${index}`}
                    showTopology={kind !== "nodeAffinity"}
                    initialTerm={initialBlock?.required?.[index]}
                    envTerm={envBlock?.required?.[index]}
                    onRemove={() => field.removeValue(index)}
                    testidRoot={`${kind}-required-row`}
                  />
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    field.pushValue(emptyAffinityTerm(defaultTopologyKey))
                  }
                >
                  Add required term
                </Button>
              </div>
            );
          }}
        </form.Field>

        {/* Preferred */}
        <form.Field name={`scheduling.${kind}.preferred`} mode="array">
          {(field: any) => {
            const rows = field.state.value ?? [];
            return (
              <div className="space-y-2">
                <Label className="font-medium">Preferred</Label>
                <p className="text-xs text-muted-foreground">
                  Soft preference — scheduler tries to honor, weighted 1–100.
                </p>
                {rows.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No preferred terms.
                  </p>
                )}
                {rows.map((_: any, index: any) => (
                  <PreferredAffinityRow
                    key={`${kind}-pref-${index}`}
                    form={form}
                    pathBase={`scheduling.${kind}.preferred.${index}`}
                    showTopology={kind !== "nodeAffinity"}
                    initialEntry={initialBlock?.preferred?.[index]}
                    envEntry={envBlock?.preferred?.[index]}
                    onRemove={() => field.removeValue(index)}
                    testidRoot={`${kind}-preferred-row`}
                  />
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    field.pushValue({
                      weight: 1,
                      term: emptyAffinityTerm(defaultTopologyKey),
                    })
                  }
                >
                  Add preferred term
                </Button>
              </div>
            );
          }}
        </form.Field>
      </div>
    </SubBlock>
  );
}

function AffinityTermEditor({
  form,
  pathBase,
  showTopology,
  initialTerm,
  envTerm,
  onRemove,
  testidRoot,
}: {
  form: ReactFormLike;
  pathBase: string;
  showTopology: boolean;
  initialTerm: AffinityTermInput | undefined;
  envTerm: AffinityTermInput | undefined;
  onRemove: () => void;
  testidRoot: string;
}) {
  return (
    <div className="space-y-3 rounded-md border p-3" data-testid={testidRoot}>
      {showTopology && (
        <form.Field name={`${pathBase}.topologyKey`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${pathBase}.topologyKey`}
              form={form}
              initial={initialTerm?.topologyKey}
              environment={envTerm?.topologyKey}
            >
              <div className="space-y-1">
                <Label>Topology key</Label>
                <Input
                  value={f.state.value ?? ""}
                  onChange={(e: any) => f.handleChange(e.target.value)}
                  placeholder="kubernetes.io/hostname"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>
      )}

      <MatchExpressionsEditor
        form={form}
        pathBase={`${pathBase}.labelSelector`}
        initial={initialTerm?.labelSelector}
        environment={envTerm?.labelSelector}
      />

      <div className="flex justify-end">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label="Remove affinity term"
          onClick={onRemove}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function PreferredAffinityRow({
  form,
  pathBase,
  showTopology,
  initialEntry,
  envEntry,
  onRemove,
  testidRoot,
}: {
  form: ReactFormLike;
  pathBase: string;
  showTopology: boolean;
  initialEntry: WeightedAffinityTermInput | undefined;
  envEntry: WeightedAffinityTermInput | undefined;
  onRemove: () => void;
  testidRoot: string;
}) {
  return (
    <div className="space-y-3 rounded-md border p-3" data-testid={testidRoot}>
      <form.Field name={`${pathBase}.weight`}>
        {(f: any) => (
          <ChangedFieldFrame
            name={`${pathBase}.weight`}
            form={form}
            initial={initialEntry?.weight}
            environment={envEntry?.weight}
          >
            <div className="space-y-1">
              <Label>Weight (1–100)</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={f.state.value ?? 1}
                onChange={(e: any) =>
                  f.handleChange(Number(e.target.value) || 1)
                }
                className="w-32"
              />
            </div>
          </ChangedFieldFrame>
        )}
      </form.Field>

      {showTopology && (
        <form.Field name={`${pathBase}.term.topologyKey`}>
          {(f: any) => (
            <ChangedFieldFrame
              name={`${pathBase}.term.topologyKey`}
              form={form}
              initial={initialEntry?.term?.topologyKey}
              environment={envEntry?.term?.topologyKey}
            >
              <div className="space-y-1">
                <Label>Topology key</Label>
                <Input
                  value={f.state.value ?? ""}
                  onChange={(e: any) => f.handleChange(e.target.value)}
                  placeholder="kubernetes.io/hostname"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>
      )}

      <MatchExpressionsEditor
        form={form}
        pathBase={`${pathBase}.term.labelSelector`}
        initial={initialEntry?.term?.labelSelector}
        environment={envEntry?.term?.labelSelector}
      />

      <div className="flex justify-end">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label="Remove preferred affinity term"
          onClick={onRemove}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// Match-expressions sub-editor — bound to `labelSelector.matchExpressions` as a
// field array. `matchLabels` is intentionally not surfaced here; the legacy
// dialog exposed both, but match-expressions is the strictly-more-general
// form, and trimming the surface keeps the chunk reviewable. (The legacy
// dialog stays available until slice 11 if operators need the dict form
// during the transition.)
function MatchExpressionsEditor({
  form,
  pathBase,
  initial,
  environment,
}: {
  form: ReactFormLike;
  pathBase: string;
  initial: LabelSelectorInput | null | undefined;
  environment: LabelSelectorInput | null | undefined;
}) {
  return (
    <form.Field name={`${pathBase}.matchExpressions`} mode="array">
      {(field: any) => {
        const rows = field.state.value ?? [];
        return (
          <div className="space-y-2 rounded-md border p-2">
            <Label className="text-xs uppercase tracking-wide">
              Match expressions
            </Label>
            {rows.length === 0 && (
              <p className="text-xs text-muted-foreground">No expressions.</p>
            )}
            {rows.map((_: any, index: any) => {
              const initialExpr = initial?.matchExpressions?.[index];
              const envExpr = environment?.matchExpressions?.[index];
              const base = `${pathBase}.matchExpressions.${index}`;
              return (
                <div
                  key={base}
                  className="flex items-start gap-2"
                  data-testid="match-expression-row"
                >
                  <form.Field name={`${base}.key`}>
                    {(f: any) => (
                      <ChangedFieldFrame
                        name={`${base}.key`}
                        form={form}
                        initial={initialExpr?.key}
                        environment={envExpr?.key}
                        className="flex-1"
                      >
                        <Input
                          aria-label="match expression key"
                          placeholder="key"
                          value={f.state.value ?? ""}
                          onChange={(e: any) => f.handleChange(e.target.value)}
                        />
                      </ChangedFieldFrame>
                    )}
                  </form.Field>
                  <form.Field name={`${base}.operator`}>
                    {(f: any) => (
                      <ChangedFieldFrame
                        name={`${base}.operator`}
                        form={form}
                        initial={initialExpr?.operator}
                        environment={envExpr?.operator}
                        className="w-36"
                      >
                        <Select
                          value={f.state.value ?? "IN"}
                          onValueChange={(v: any) => f.handleChange(v)}
                        >
                          <SelectTrigger aria-label="operator">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {["IN", "NOT_IN", "EXISTS", "DOES_NOT_EXIST"].map(
                              (op: any) => (
                                <SelectItem key={op} value={op}>
                                  {op}
                                </SelectItem>
                              ),
                            )}
                          </SelectContent>
                        </Select>
                      </ChangedFieldFrame>
                    )}
                  </form.Field>
                  <form.Field name={`${base}.values`}>
                    {(f: any) => (
                      <ChangedFieldFrame
                        name={`${base}.values`}
                        form={form}
                        initial={initialExpr?.values}
                        environment={envExpr?.values}
                        className="flex-1"
                      >
                        <Input
                          aria-label="match expression values"
                          placeholder="values (comma-separated)"
                          value={(f.state.value ?? []).join(",")}
                          onChange={(e: any) =>
                            f.handleChange(
                              e.target.value === ""
                                ? undefined
                                : e.target.value
                                    .split(",")
                                    .map((s: any) => s.trim())
                                    .filter(Boolean),
                            )
                          }
                        />
                      </ChangedFieldFrame>
                    )}
                  </form.Field>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove expression ${index + 1}`}
                    onClick={() => field.removeValue(index)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              );
            })}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => field.pushValue({ key: "", operator: "IN" })}
            >
              Add expression
            </Button>
          </div>
        );
      }}
    </form.Field>
  );
}
