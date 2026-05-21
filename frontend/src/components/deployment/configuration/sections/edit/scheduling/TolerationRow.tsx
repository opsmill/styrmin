/* eslint-disable @typescript-eslint/no-explicit-any */
import { X } from "lucide-react";

import type { ReactFormLike } from "../types";

import type {
  SchedulingInput,
  TolerationEffect,
  TolerationOperator,
} from "@/generated/graphql";
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
import { TOLERATION_EFFECTS, TOLERATION_OPERATORS } from "./schema";

interface Props {
  index: number;
  form: ReactFormLike;
  initialScheduling: SchedulingInput;
  envScheduling: SchedulingInput;
  onRemove: () => void;
}

export function TolerationRow({
  index,
  form,
  initialScheduling,
  envScheduling,
  onRemove,
}: Props) {
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
                    {TOLERATION_OPERATORS.map((op) => (
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
                    {TOLERATION_EFFECTS.map((ef) => (
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
