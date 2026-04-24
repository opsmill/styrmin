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
import type { Toleration, TolerationEffect, TolerationOperator } from "./types";
import { TOLERATION_EFFECTS, TOLERATION_OPERATORS } from "./types";

interface Props {
  value: Toleration[];
  onChange: (next: Toleration[]) => void;
}

export function TolerationsEditor({ value, onChange }: Props) {
  function updateAt(i: number, patch: Partial<Toleration>): void {
    const next = value.map((t, idx) => (idx === i ? { ...t, ...patch } : t));
    onChange(next);
  }

  function removeAt(i: number): void {
    onChange(value.filter((_, idx) => idx !== i));
  }

  function add(): void {
    onChange([...value, { operator: "Equal", effect: "NoSchedule" }]);
  }

  return (
    <div className="space-y-3">
      {value.length === 0 && (
        <p className="text-xs text-muted-foreground">No tolerations.</p>
      )}
      {value.map((t, i) => (
        <div
          key={`tol-${i}`}
          className="space-y-2 rounded-md border p-3"
          data-testid="toleration-row"
        >
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label htmlFor={`tol-key-${i}`}>Key</Label>
              <Input
                id={`tol-key-${i}`}
                value={t.key ?? ""}
                onChange={(e) => updateAt(i, { key: e.target.value })}
                placeholder="e.g. dedicated"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`tol-operator-${i}`}>Operator</Label>
              <Select
                value={t.operator ?? "Equal"}
                onValueChange={(v) =>
                  updateAt(i, { operator: v as TolerationOperator })
                }
              >
                <SelectTrigger id={`tol-operator-${i}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TOLERATION_OPERATORS.map((op) => (
                    <SelectItem key={op} value={op}>
                      {op}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor={`tol-value-${i}`}>Value</Label>
              <Input
                id={`tol-value-${i}`}
                value={t.value ?? ""}
                onChange={(e) => updateAt(i, { value: e.target.value })}
                placeholder="e.g. batch"
                disabled={t.operator === "Exists"}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`tol-effect-${i}`}>Effect</Label>
              <Select
                value={t.effect ?? "NoSchedule"}
                onValueChange={(v) =>
                  updateAt(i, { effect: v as TolerationEffect })
                }
              >
                <SelectTrigger id={`tol-effect-${i}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TOLERATION_EFFECTS.map((ef) => (
                    <SelectItem key={ef} value={ef}>
                      {ef}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex items-end justify-between gap-2">
            <div className="space-y-1">
              <Label htmlFor={`tol-seconds-${i}`}>
                Toleration seconds (optional)
              </Label>
              <Input
                id={`tol-seconds-${i}`}
                type="number"
                min={0}
                value={t.toleration_seconds ?? ""}
                onChange={(e) =>
                  updateAt(i, {
                    toleration_seconds:
                      e.target.value === ""
                        ? undefined
                        : Number(e.target.value),
                  })
                }
                placeholder="only for NoExecute"
                className="w-48"
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`Remove toleration ${i + 1}`}
              onClick={() => removeAt(i)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        Add toleration
      </Button>
    </div>
  );
}
