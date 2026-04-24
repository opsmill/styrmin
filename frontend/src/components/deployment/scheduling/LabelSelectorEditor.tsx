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
import type {
  LabelSelector,
  LabelSelectorOperator,
  LabelSelectorRequirement,
} from "./types";
import { LABEL_SELECTOR_OPERATORS } from "./types";

interface Props {
  value: LabelSelector | undefined;
  onChange: (next: LabelSelector | undefined) => void;
  idPrefix: string;
}

export function LabelSelectorEditor({ value, onChange, idPrefix }: Props) {
  const matchLabels = Object.entries(value?.match_labels ?? {});
  const matchExpressions = value?.match_expressions ?? [];

  function update(next: LabelSelector): void {
    const hasLabels = Object.keys(next.match_labels ?? {}).length > 0;
    const hasExpressions = (next.match_expressions ?? []).length > 0;
    onChange(hasLabels || hasExpressions ? next : undefined);
  }

  function setMatchLabel(index: number, key: string, val: string): void {
    const nextEntries = [...matchLabels];
    nextEntries[index] = [key, val];
    update({
      ...value,
      match_labels: Object.fromEntries(nextEntries.filter(([k]) => k !== "")),
    });
  }

  function removeMatchLabel(index: number): void {
    const nextEntries = matchLabels.filter((_, i) => i !== index);
    update({ ...value, match_labels: Object.fromEntries(nextEntries) });
  }

  function addMatchLabel(): void {
    update({
      ...value,
      match_labels: { ...(value?.match_labels ?? {}), "": "" },
    });
  }

  function setExpression(
    index: number,
    patch: Partial<LabelSelectorRequirement>,
  ): void {
    const next = matchExpressions.map((e, i) =>
      i === index ? { ...e, ...patch } : e,
    );
    update({ ...value, match_expressions: next });
  }

  function removeExpression(index: number): void {
    update({
      ...value,
      match_expressions: matchExpressions.filter((_, i) => i !== index),
    });
  }

  function addExpression(): void {
    update({
      ...value,
      match_expressions: [...matchExpressions, { key: "", operator: "In" }],
    });
  }

  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="space-y-2">
        <Label>Match labels</Label>
        {matchLabels.length === 0 && (
          <p className="text-xs text-muted-foreground">No match labels.</p>
        )}
        {matchLabels.map(([k, v], i) => (
          <div
            key={`${idPrefix}-ml-${i}`}
            className="flex items-center gap-2"
            data-testid="match-label-row"
          >
            <Input
              aria-label={`${idPrefix} match label key ${i + 1}`}
              placeholder="key"
              value={k}
              onChange={(e) => setMatchLabel(i, e.target.value, v)}
            />
            <Input
              aria-label={`${idPrefix} match label value ${i + 1}`}
              placeholder="value"
              value={v}
              onChange={(e) => setMatchLabel(i, k, e.target.value)}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`Remove match label ${i + 1}`}
              onClick={() => removeMatchLabel(i)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addMatchLabel}
        >
          Add match label
        </Button>
      </div>

      <div className="space-y-2">
        <Label>Match expressions</Label>
        {matchExpressions.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No match expressions.
          </p>
        )}
        {matchExpressions.map((expr, i) => (
          <div
            key={`${idPrefix}-me-${i}`}
            className="flex items-start gap-2"
            data-testid="match-expression-row"
          >
            <Input
              aria-label={`${idPrefix} expression key ${i + 1}`}
              placeholder="key"
              value={expr.key}
              onChange={(e) => setExpression(i, { key: e.target.value })}
              className="flex-1"
            />
            <Select
              value={expr.operator}
              onValueChange={(v) =>
                setExpression(i, { operator: v as LabelSelectorOperator })
              }
            >
              <SelectTrigger
                aria-label={`${idPrefix} expression operator ${i + 1}`}
                className="w-36"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LABEL_SELECTOR_OPERATORS.map((op) => (
                  <SelectItem key={op} value={op}>
                    {op}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label={`${idPrefix} expression values ${i + 1}`}
              placeholder="values (comma-separated)"
              value={(expr.values ?? []).join(",")}
              onChange={(e) =>
                setExpression(i, {
                  values: e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              className="flex-1"
              disabled={
                expr.operator === "Exists" || expr.operator === "DoesNotExist"
              }
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`Remove match expression ${i + 1}`}
              onClick={() => removeExpression(i)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addExpression}
        >
          Add match expression
        </Button>
      </div>
    </div>
  );
}
