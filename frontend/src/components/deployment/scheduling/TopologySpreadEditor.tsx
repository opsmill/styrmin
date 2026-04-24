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
import { X } from "lucide-react";
import { LabelSelectorEditor } from "./LabelSelectorEditor";
import type { TopologySpreadConstraint, WhenUnsatisfiable } from "./types";
import { WHEN_UNSATISFIABLE } from "./types";

interface Props {
  value: TopologySpreadConstraint[];
  onChange: (next: TopologySpreadConstraint[]) => void;
}

export function TopologySpreadEditor({ value, onChange }: Props) {
  function updateAt(
    i: number,
    patch: Partial<TopologySpreadConstraint>,
  ): void {
    onChange(value.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }

  function removeAt(i: number): void {
    onChange(value.filter((_, idx) => idx !== i));
  }

  function add(): void {
    onChange([
      ...value,
      {
        max_skew: 1,
        topology_key: "kubernetes.io/hostname",
        when_unsatisfiable: "ScheduleAnyway",
      },
    ]);
  }

  return (
    <div className="space-y-3">
      {value.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No topology spread constraints.
        </p>
      )}
      {value.map((c, i) => (
        <div
          key={`tsc-${i}`}
          className="space-y-3 rounded-md border p-3"
          data-testid="topology-spread-row"
        >
          <div className="grid grid-cols-3 gap-2">
            <div className="space-y-1">
              <Label htmlFor={`tsc-skew-${i}`}>Max skew</Label>
              <Input
                id={`tsc-skew-${i}`}
                type="number"
                min={1}
                value={c.max_skew}
                onChange={(e) =>
                  updateAt(i, { max_skew: Number(e.target.value) || 1 })
                }
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`tsc-topology-${i}`}>Topology key</Label>
              <Input
                id={`tsc-topology-${i}`}
                value={c.topology_key}
                onChange={(e) => updateAt(i, { topology_key: e.target.value })}
                placeholder="e.g. kubernetes.io/hostname"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`tsc-when-${i}`}>When unsatisfiable</Label>
              <Select
                value={c.when_unsatisfiable}
                onValueChange={(v) =>
                  updateAt(i, { when_unsatisfiable: v as WhenUnsatisfiable })
                }
              >
                <SelectTrigger id={`tsc-when-${i}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WHEN_UNSATISFIABLE.map((wu) => (
                    <SelectItem key={wu} value={wu}>
                      {wu}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <LabelSelectorEditor
            value={c.label_selector}
            onChange={(ls) => updateAt(i, { label_selector: ls })}
            idPrefix={`tsc-${i}`}
          />
          <div className="flex justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`Remove topology spread constraint ${i + 1}`}
              onClick={() => removeAt(i)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        Add topology spread constraint
      </Button>
    </div>
  );
}
