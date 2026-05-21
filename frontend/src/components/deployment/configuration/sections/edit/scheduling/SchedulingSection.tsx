/* eslint-disable @typescript-eslint/no-explicit-any */
import type { ReactFormLike } from "../types";

import type {
  PostRenderInjectionInput,
  SchedulingInput,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SectionId } from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../../ChangedFieldFrame";
import { useDrawerDiff } from "../../../DrawerDiffContext";

import { AffinityBlock } from "./AffinityBlock";
import {
  INJECTION_LABELS,
  emptyToleration,
  emptyTopologySpread,
} from "./schema";
import { SubBlock } from "./SubBlock";
import { TolerationRow } from "./TolerationRow";
import { TopologySpreadRow } from "./TopologySpreadRow";

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  anchorId: SectionId;
}

/**
 * Scheduling section of the edit drawer. Binds the form's `scheduling.*`
 * sub-paths to the drawer's single TanStack Form instance via `form.Field`.
 *
 * Sub-blocks (top-to-bottom):
 *   - Resources (request/limit for CPU + memory)
 *   - Tolerations (field array of {@link TolerationRow})
 *   - Topology spread (field array of {@link TopologySpreadRow})
 *   - Node affinity, Pod affinity, Pod anti-affinity (three {@link AffinityBlock}
 *     instances; same shape, different topology defaults)
 *   - Runtime class
 *   - Post-render injection toggles (per `PostRenderInjectionInput`)
 *
 * Every leaf input is wrapped in {@link ChangedFieldFrame} so the amber
 * outline and "from X (env)" annotation render uniformly across the drawer.
 *
 * The component was split out of a single 1.3k-LoC file into this
 * subdirectory so each sub-block can be reviewed and tested in isolation.
 */
export function SchedulingSection({
  form,
  initial,
  environment,
  anchorId,
}: Props) {
  const initialScheduling = (initial.scheduling ?? {}) as SchedulingInput;
  const envScheduling = (environment.scheduling ?? {}) as SchedulingInput;

  const changedCount = useDrawerDiff().entries.filter(
    (e) => e.section === anchorId,
  ).length;

  return (
    <section
      data-section={anchorId}
      id={`${anchorId}-anchor`}
      className="scroll-mt-4"
    >
      <div className="mb-3 flex items-center gap-3">
        <h3
          id={`${anchorId}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-foreground"
        >
          Scheduling
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
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

        {/* ── Node / Pod / Pod-Anti affinity ──────────────────────── */}
        <AffinityBlock
          kind="nodeAffinity"
          label="Node affinity"
          description="Schedule pods to nodes whose labels match."
          form={form}
          initialScheduling={initialScheduling}
          envScheduling={envScheduling}
        />
        <AffinityBlock
          kind="podAffinity"
          label="Pod affinity"
          description="Co-locate pods with matching peers."
          form={form}
          initialScheduling={initialScheduling}
          envScheduling={envScheduling}
        />
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
