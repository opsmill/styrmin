/* eslint-disable @typescript-eslint/no-explicit-any */
import type { ReactFormLike } from "../types";

import type { AffinityBlockInput, SchedulingInput } from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

import { AffinityTermEditor } from "./AffinityTermEditor";
import { PreferredAffinityRow } from "./PreferredAffinityRow";
import { SubBlock } from "./SubBlock";
import { emptyAffinityTerm, type AffinityKind } from "./schema";

interface Props {
  kind: AffinityKind;
  label: string;
  description: string;
  form: ReactFormLike;
  initialScheduling: SchedulingInput;
  envScheduling: SchedulingInput;
}

/**
 * Single affinity block — required + preferred lists for Node, Pod, or
 * PodAnti affinity. Node affinity does not surface a topology key (it
 * matches on node labels directly); pod-level kinds do.
 */
export function AffinityBlock({
  kind,
  label,
  description,
  form,
  initialScheduling,
  envScheduling,
}: Props) {
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
