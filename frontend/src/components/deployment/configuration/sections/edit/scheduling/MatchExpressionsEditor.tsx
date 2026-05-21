/* eslint-disable @typescript-eslint/no-explicit-any */
import { X } from "lucide-react";

import type { ReactFormLike } from "../types";

import type { LabelSelectorInput } from "@/generated/graphql";
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

/**
 * Match-expressions sub-editor — bound to `labelSelector.matchExpressions`
 * as a field array. `matchLabels` is intentionally not surfaced here; the
 * legacy dialog exposed both, but match-expressions is the strictly-more-
 * general form, and trimming the surface keeps the drawer readable.
 */
export function MatchExpressionsEditor({
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
