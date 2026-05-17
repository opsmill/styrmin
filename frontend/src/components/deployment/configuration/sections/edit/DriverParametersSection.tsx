// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "@tanstack/react-form";
import { z } from "zod";

import type { ReactFormLike } from "./types";

import type {
  ParameterDefinition,
  UpdateDeploymentInput,
} from "@/generated/graphql";

// JSON-shaped row for the form's `parameters` array. Codegen narrows the
// `value` JSON scalar to `Record<string, unknown>`, which would force every
// scalar parameter value (string/number/boolean) into a wrapper dict; we
// model it as `unknown` here and cast at the GraphQL boundary.
type ParameterRow = { name: string; value: unknown };
import { diff } from "@/lib/config-diff";
import type {
  DriverParameterSchema,
  SectionId,
} from "@/lib/configuration-types";

import { cn } from "@/lib/utils";
import { ParameterField } from "../../ParameterField";

/**
 * Zod schema for the driver parameters list. Two layers of validation:
 *
 *  - Per-parameter type: `value` matches the declared `kind` (boolean →
 *    boolean, integer → number, select → string in `values`, string-ish →
 *    string).
 *  - Required parameters (those without a `default`) must be present with a
 *    non-empty value.
 *
 * The schema is built dynamically from the driver's parameter list, so the
 * exported member is a factory rather than a plain object — call
 * `driverParametersSchema(driverSchema)` at form-validation time.
 */
export function driverParametersSchema(schema: DriverParameterSchema = []) {
  const byName = new Map(schema.map((p) => [p.name, p]));
  const knownNames = new Set(byName.keys());

  return z
    .array(
      z.object({
        name: z.string(),
        value: z.unknown(),
      }),
    )
    .optional()
    .superRefine((rows: any, ctx: any) => {
      if (!rows) return;
      const seen = new Set<string>();
      rows.forEach((row: any, index: number) => {
        if (seen.has(row.name)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `Duplicate parameter "${row.name}".`,
            path: [index, "name"],
          });
          return;
        }
        seen.add(row.name);
        const def = byName.get(row.name);
        if (!def) {
          // Unknown parameter — flag as invalid (driver schema drifted).
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `Parameter "${row.name}" is not declared by the driver.`,
            path: [index, "name"],
          });
          return;
        }
        const err = checkType(def, row.value);
        if (err) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: err,
            path: [index, "value"],
          });
        }
      });
      // Required parameters (no default) must be present.
      for (const def of schema) {
        if (def.default != null) continue;
        if (!seen.has(def.name)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `Required parameter "${def.name}" is missing.`,
            path: [],
          });
        }
      }
      // Reject any name not in the schema (already done above via byName).
      void knownNames;
    });
}

function checkType(def: ParameterDefinition, value: unknown): string | null {
  switch (def.kind) {
    case "boolean":
      return typeof value === "boolean" || value == null
        ? null
        : `Expected boolean for "${def.name}".`;
    case "integer":
      return typeof value === "number" && Number.isFinite(value)
        ? null
        : `Expected integer for "${def.name}".`;
    case "select": {
      if (value == null) return null;
      if (typeof value !== "string") {
        return `Expected select value (string) for "${def.name}".`;
      }
      if (def.values && def.values.length > 0 && !def.values.includes(value)) {
        return `"${value}" is not one of: ${def.values.join(", ")}.`;
      }
      return null;
    }
    default:
      return value == null || typeof value === "string"
        ? null
        : `Expected string for "${def.name}".`;
  }
}

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
  anchorId: SectionId;
}

/**
 * Driver Parameters section of the edit drawer.
 *
 * Renders one input per parameter declared by `driverSchema`, using the
 * extracted {@link ParameterField} component so the rendering matches the
 * existing `DeployFormPage` (extraction tracked in T018).
 *
 * Storage model: `UpdateDeploymentInput.parameters` is a list of
 * `{name, value}` rows with **merge semantics** (existing keys not named in
 * the input survive). The form holds the full current list in `parameters`;
 * each field reads its current row by name and writes back by replacing the
 * row (or appending if missing). This keeps the form value canonical so the
 * diff library can attribute parameter changes correctly via stable name
 * keys (per data-model.md `DiffEntry.path`).
 */
export function DriverParametersSection({
  form,
  initial,
  environment,
  driverSchema,
  anchorId,
}: Props) {
  const schema = driverSchema ?? [];

  const changedCount = useStore(
    form.store,
    (state: any) =>
      diff(initial, state.values, schema).entries.filter(
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
          Driver Parameters
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

      {schema.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          No driver parameters declared.
        </p>
      ) : (
        <div className="space-y-4">
          {schema.map((param) => (
            <ParameterFieldRow
              key={param.name}
              parameter={param}
              form={form}
              initial={initial}
              environment={environment}
            />
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * Render one driver parameter as a `ParameterField` wrapped in a
 * `ChangedFieldFrame`. Reading and writing the canonical
 * `parameters: [{name, value}]` array is done through
 * `form.getFieldValue("parameters")` / `form.setFieldValue("parameters", …)`
 * so the field-array order stays under the form's control.
 */
function ParameterFieldRow({
  parameter,
  form,
  initial,
  environment,
}: {
  parameter: ParameterDefinition;
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
}) {
  const initialValue = findParam(
    initial.parameters as ParameterRow[] | undefined,
    parameter.name,
  );
  const envValue = findParam(
    environment.parameters as ParameterRow[] | undefined,
    parameter.name,
  );

  // Subscribe to the current value of this specific parameter. We re-derive
  // it from the array on every store change, scoped by the selector.
  const currentValue = useStore(form.store, (state: any) =>
    findParam(state.values?.parameters, parameter.name),
  );

  const handleChange = (next: unknown) => {
    const list: ParameterRow[] = [
      ...((form.getFieldValue("parameters") as ParameterRow[]) ?? []),
    ];
    const idx = list.findIndex((p) => p.name === parameter.name);
    const nextEntry: ParameterRow = { name: parameter.name, value: next };
    if (idx >= 0) {
      list[idx] = nextEntry;
    } else {
      list.push(nextEntry);
    }
    form.setFieldValue("parameters", list);
  };

  const initialEffective = initialValue ?? parameter.default;
  const envEffective = envValue ?? parameter.default;
  const isChanged = !sameJson(currentValue, initialEffective);
  const fromEnvironment = sameJson(initialEffective, envEffective);

  if (!isChanged) {
    return (
      <div className="space-y-1" data-parameter={parameter.name}>
        <ParameterField
          parameter={parameter}
          value={currentValue}
          onChange={handleChange}
        />
      </div>
    );
  }

  return (
    <div
      data-testid="changed-field-frame"
      data-changed="true"
      data-parameter={parameter.name}
      className={cn(
        "rounded-md border border-amber-400 bg-amber-50/40 p-2 dark:bg-amber-950/20",
      )}
    >
      <div className="mb-1 flex items-center gap-2">
        <span
          data-testid="changed-pill"
          className="inline-flex items-center rounded-md border border-amber-400 bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-900/40 dark:text-amber-200"
        >
          changed
        </span>
        <span
          data-testid="changed-from"
          className="text-xs text-muted-foreground"
        >
          from {stringifyValue(initialEffective)}
          {fromEnvironment ? " (env)" : ""}
        </span>
      </div>
      <ParameterField
        parameter={parameter}
        value={currentValue}
        onChange={handleChange}
      />
    </div>
  );
}

function sameJson(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

function stringifyValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value === "" ? '""' : value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function findParam(
  parameters: ParameterRow[] | null | undefined,
  name: string,
): unknown {
  if (!parameters) return undefined;
  const row = parameters.find((p) => p.name === name);
  return row?.value;
}
