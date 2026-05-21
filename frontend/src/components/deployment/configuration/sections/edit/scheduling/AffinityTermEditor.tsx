/* eslint-disable @typescript-eslint/no-explicit-any */
import { X } from "lucide-react";

import type { ReactFormLike } from "../types";

import type { AffinityTermInput } from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { ChangedFieldFrame } from "../../../ChangedFieldFrame";
import { MatchExpressionsEditor } from "./MatchExpressionsEditor";

interface Props {
  form: ReactFormLike;
  pathBase: string;
  showTopology: boolean;
  initialTerm: AffinityTermInput | undefined;
  envTerm: AffinityTermInput | undefined;
  onRemove: () => void;
  testidRoot: string;
}

export function AffinityTermEditor({
  form,
  pathBase,
  showTopology,
  initialTerm,
  envTerm,
  onRemove,
  testidRoot,
}: Props) {
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
