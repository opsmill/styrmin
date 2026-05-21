/* eslint-disable @typescript-eslint/no-explicit-any */
import { X } from "lucide-react";

import type { ReactFormLike } from "../types";

import type { WeightedAffinityTermInput } from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { ChangedFieldFrame } from "../../../ChangedFieldFrame";
import { MatchExpressionsEditor } from "./MatchExpressionsEditor";

interface Props {
  form: ReactFormLike;
  pathBase: string;
  showTopology: boolean;
  initialEntry: WeightedAffinityTermInput | undefined;
  envEntry: WeightedAffinityTermInput | undefined;
  onRemove: () => void;
  testidRoot: string;
}

export function PreferredAffinityRow({
  form,
  pathBase,
  showTopology,
  initialEntry,
  envEntry,
  onRemove,
  testidRoot,
}: Props) {
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
