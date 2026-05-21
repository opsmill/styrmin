/* eslint-disable @typescript-eslint/no-explicit-any */
import { X } from "lucide-react";

import type { ReactFormLike } from "../types";

import type { SchedulingInput, WhenUnsatisfiable } from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { ChangedFieldFrame } from "../../../ChangedFieldFrame";
import { WHEN_UNSATISFIABLE } from "./schema";

interface Props {
  index: number;
  form: ReactFormLike;
  initialScheduling: SchedulingInput;
  envScheduling: SchedulingInput;
  onRemove: () => void;
}

export function TopologySpreadRow({
  index,
  form,
  initialScheduling,
  envScheduling,
  onRemove,
}: Props) {
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
                    {WHEN_UNSATISFIABLE.map((w) => (
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
