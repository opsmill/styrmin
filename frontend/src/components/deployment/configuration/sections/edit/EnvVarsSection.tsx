// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "@tanstack/react-form";
import { X } from "lucide-react";
import { z } from "zod";

import type { ReactFormLike } from "./types";

import type { EnvVarInput, UpdateDeploymentInput } from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { diff } from "@/lib/config-diff";
import type {
  DriverParameterSchema,
  SectionId,
} from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";

// POSIX env-var name regex per data-model.md: must start with a letter or
// underscore and continue with letters, digits, or underscores.
const POSIX_ENV_VAR = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * Zod schema for the deployment-scoped env-var override list.
 *
 * Rules (data-model.md "Env Vars" row):
 *  - `name` matches the POSIX env-var regex.
 *  - `value` may be any string (including empty — explicit override to "").
 *  - Names must be unique within the list. Duplicates surface as row-level
 *    errors via {@link superRefine} so each offending row gets its own marker.
 */
export const envVarsSchema = z
  .array(
    z.object({
      name: z.string().regex(POSIX_ENV_VAR, {
        message:
          "Must be a valid POSIX env-var name (letters, digits, underscore; cannot start with digit).",
      }),
      value: z.string(),
    }),
  )
  .superRefine((rows: any, ctx: any) => {
    const seen = new Map<string, number>();
    rows.forEach((row: any, index: number) => {
      const previous = seen.get(row.name);
      if (previous !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `Duplicate env var "${row.name}" (also at row ${previous + 1}).`,
          path: [index, "name"],
        });
      } else {
        seen.set(row.name, index);
      }
    });
  });

function emptyRow(): EnvVarInput {
  return { name: "", value: "" };
}

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
  anchorId: SectionId;
}

/**
 * Env Vars section of the edit drawer.
 *
 * Field array over `envVars: { name, value }[]`. Each row is two inputs +
 * remove button; an add-row button at the bottom appends an empty entry.
 *
 * Inheritance: the parent environment's `envVars` are NOT displayed here —
 * the read-side `EnvVarsSummary` shows the "+ N inherited from environment"
 * footer. The edit surface intentionally focuses on the deployment-scoped
 * override list since that is the only thing this mutation can write.
 */
export function EnvVarsSection({
  form,
  initial,
  environment,
  anchorId,
}: Props) {
  const initialRows = (initial.envVars ?? []) as EnvVarInput[];
  const envRows = (environment.envVars ?? []) as EnvVarInput[];
  const envCount = envRows.length;

  const changedCount = useStore(
    form.store,
    (state: any) =>
      diff(initial, state.values, [] as DriverParameterSchema).entries.filter(
        (e: any) => e.section === anchorId,
      ).length,
  );

  return (
    <section
      data-section={anchorId}
      id={`${anchorId}-anchor`}
      className="scroll-mt-4"
    >
      <div className="mb-3 flex items-center gap-3">
        <h3
          id={`${anchorId}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-slate-700"
        >
          Environment Vars
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900"
          >
            {changedCount} changed
          </span>
        )}
      </div>

      <form.Field name="envVars" mode="array">
        {(field: any) => {
          const rows: EnvVarInput[] = field.state.value ?? [];
          return (
            <div className="space-y-3">
              {rows.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No deployment-scoped env vars.
                </p>
              )}
              {rows.map((_row, index) => {
                const base = `envVars.${index}` as const;
                const initialRow = initialRows[index];
                const envRow = envRows[index];
                return (
                  <div
                    key={`envvar-${index}`}
                    className="grid grid-cols-[1fr_1fr_auto] items-start gap-2 rounded-md border p-3"
                    data-testid="env-var-row"
                  >
                    <form.Field name={`${base}.name`}>
                      {(f: any) => (
                        <ChangedFieldFrame
                          name={`${base}.name`}
                          form={form}
                          initial={initialRow?.name}
                          environment={envRow?.name}
                        >
                          <div className="space-y-1">
                            <Label htmlFor={`envvar-name-${index}`}>Name</Label>
                            <Input
                              id={`envvar-name-${index}`}
                              data-testid={`envvar-name-${index}`}
                              value={f.state.value ?? ""}
                              onChange={(e: any) =>
                                f.handleChange(e.target.value)
                              }
                              onBlur={f.handleBlur}
                              placeholder="LOG_LEVEL"
                              autoComplete="off"
                            />
                            {f.state.meta.errors.length > 0 && (
                              <p className="text-xs text-destructive">
                                {String(f.state.meta.errors[0])}
                              </p>
                            )}
                          </div>
                        </ChangedFieldFrame>
                      )}
                    </form.Field>
                    <form.Field name={`${base}.value`}>
                      {(f: any) => (
                        <ChangedFieldFrame
                          name={`${base}.value`}
                          form={form}
                          initial={initialRow?.value}
                          environment={envRow?.value}
                        >
                          <div className="space-y-1">
                            <Label htmlFor={`envvar-value-${index}`}>
                              Value
                            </Label>
                            <Input
                              id={`envvar-value-${index}`}
                              data-testid={`envvar-value-${index}`}
                              value={f.state.value ?? ""}
                              onChange={(e: any) =>
                                f.handleChange(e.target.value)
                              }
                              onBlur={f.handleBlur}
                              placeholder="info"
                              autoComplete="off"
                            />
                          </div>
                        </ChangedFieldFrame>
                      )}
                    </form.Field>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove env var ${index + 1}`}
                      data-testid={`envvar-remove-${index}`}
                      onClick={() => field.removeValue(index)}
                      className="mt-6"
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
                data-testid="add-env-var"
                onClick={() => field.pushValue(emptyRow())}
              >
                Add env var
              </Button>
              {envCount > 0 && (
                <p className="text-xs italic text-muted-foreground">
                  + {envCount} inherited from environment (read-only here).
                </p>
              )}
            </div>
          );
        }}
      </form.Field>
    </section>
  );
}
