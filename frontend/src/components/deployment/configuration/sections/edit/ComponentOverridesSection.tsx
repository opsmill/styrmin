// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "@tanstack/react-form";
import { ChevronDown, X } from "lucide-react";
import { z } from "zod";

import type { ReactFormLike } from "./types";

import type {
  ComponentConfigInput,
  EnvVarInput,
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { diff } from "@/lib/config-diff";
import type {
  DriverParameterSchema,
  SectionId,
} from "@/lib/configuration-types";
import { cn } from "@/lib/utils";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";

type DeploymentComponent = NonNullable<
  GetDeploymentQuery["deployment"]
>["components"][number];

// POSIX env-var name regex — mirrors `EnvVarsSection`.
const POSIX_ENV_VAR = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * Zod schema for the per-component override list (`UpdateDeploymentInput.components`).
 *
 * Today the backend `ComponentConfigInput` only accepts a name + an env-var
 * list. Future per-component knobs (CPU/memory, replicas, image overrides)
 * are intentionally rendered as muted "coming soon" placeholders in the UI
 * so the section has visible room to grow without restructuring; they are
 * **not** part of this validation schema until the GraphQL surface widens.
 *
 * Rules:
 *  - `name` non-empty (driver-declared component name; backend re-validates).
 *  - `envVars[*].name` matches the POSIX env-var regex.
 *  - Per-component env-var names are unique within that block.
 *  - Per-component `name` is unique across the whole list (one block per
 *    component).
 */
export const componentOverridesSchema = z
  .array(
    z.object({
      name: z.string().min(1, "Component name is required"),
      envVars: z
        .array(
          z.object({
            name: z.string().regex(POSIX_ENV_VAR, {
              message:
                "Must be a valid POSIX env-var name (letters, digits, underscore; cannot start with digit).",
            }),
            value: z.string(),
          }),
        )
        .optional()
        .superRefine((rows: any, ctx: any) => {
          if (!rows) return;
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
        }),
    }),
  )
  .superRefine((rows: any, ctx: any) => {
    const seen = new Map<string, number>();
    rows.forEach((row: any, index: number) => {
      const previous = seen.get(row.name);
      if (previous !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `Component "${row.name}" already overridden at row ${
            previous + 1
          }.`,
          path: [index, "name"],
        });
      } else {
        seen.set(row.name, index);
      }
    });
  });

function emptyEnvVar(): EnvVarInput {
  return { name: "", value: "" };
}

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
  anchorId: SectionId;
  /** All components declared by the deployment's currently-pinned driver. */
  components: readonly DeploymentComponent[];
}

interface ComponentOverridesField {
  state: { value: ComponentConfigInput[] | null | undefined };
  pushValue: (value: ComponentConfigInput) => void;
  removeValue: (index: number) => void;
}

/**
 * Lazily create the per-component override block keyed by the stable
 * component name (idempotent: no-op when a block for this component
 * already exists).
 *
 * The chunk decision is explicit: field-array semantics are keyed by name,
 * never positional — the order in the form-state array carries no meaning,
 * and any consumer that depends on it is broken by design.
 */
function ensureComponentBlock(
  field: ComponentOverridesField,
  name: string,
): void {
  const rows = field.state.value ?? [];
  if (rows.some((row) => row?.name === name)) return;
  field.pushValue({ name, envVars: [] });
}

/**
 * Component Overrides section of the edit drawer (FR-013).
 *
 * One Base UI Collapsible per driver-declared component. Inside the body:
 *  - Per-component env-var field array (the only over­ride scope wired
 *    end-to-end today; lines up with `ComponentConfigInput.envVars`).
 *  - A muted "future per-component fields (CPU / memory / replicas)
 *    coming in future iterations" line so the section has visible room to
 *    grow without a structural rewrite.
 *
 * Field-array semantics: every read or write into the override list keys
 * on the component `name`. The array index is an implementation detail of
 * TanStack Form's `mode="array"`; it never appears in the diff path (which
 * is `components[<name>].…` — see `config-diff.ts`).
 */
export function ComponentOverridesSection({
  form,
  initial,
  environment,
  anchorId,
  components,
}: Props) {
  const initialBlocks = (initial.components ?? []) as ComponentConfigInput[];
  const envBlocks = (environment.components ?? []) as ComponentConfigInput[];
  const initialByName = new Map(initialBlocks.map((b) => [b.name, b] as const));
  const envByName = new Map(envBlocks.map((b) => [b.name, b] as const));

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
          className="text-sm font-semibold uppercase tracking-wide text-foreground"
        >
          Component Overrides
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
          >
            {changedCount} changed
          </span>
        )}
      </div>

      <form.Field name="components" mode="array">
        {(field: ComponentOverridesField) => {
          const rows: ComponentConfigInput[] = field.state.value ?? [];
          const rowIndexByName = new Map(
            rows.map((row, index) => [row.name, index] as const),
          );

          if (components.length === 0) {
            return (
              <p className="text-xs italic text-muted-foreground">
                The pinned driver declares no components.
              </p>
            );
          }

          return (
            <div className="space-y-3">
              {components.map((component) => {
                const componentName = component.name;
                const overrideIndex = rowIndexByName.get(componentName);
                const overrideRow =
                  overrideIndex !== undefined ? rows[overrideIndex] : undefined;
                const hasOverride = overrideRow !== undefined;
                const envVarCount = overrideRow?.envVars?.length ?? 0;

                return (
                  <Collapsible
                    key={component.id}
                    data-testid="component-override-block"
                    data-component={componentName}
                    className="rounded-md border border-border bg-card"
                  >
                    <CollapsibleTrigger
                      data-testid={`component-override-trigger-${componentName}`}
                      className="group flex w-full items-center justify-between gap-3 px-3 py-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="flex items-center gap-2">
                        <ChevronDown
                          aria-hidden="true"
                          className="h-4 w-4 text-muted-foreground transition-transform group-data-[panel-open]:rotate-0 group-data-[panel-closed]:-rotate-90"
                        />
                        <span className="font-mono text-xs text-foreground">
                          {componentName}
                        </span>
                        {hasOverride && (
                          <span
                            data-testid={`component-override-pill-${componentName}`}
                            className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-800 dark:bg-blue-950/40 dark:text-blue-300"
                          >
                            override
                          </span>
                        )}
                      </span>
                      <span className="text-[11px] text-muted-foreground">
                        {hasOverride
                          ? `${envVarCount} env var${envVarCount === 1 ? "" : "s"}`
                          : "no override"}
                      </span>
                    </CollapsibleTrigger>
                    <CollapsibleContent
                      className={cn("border-t border-border px-3 py-3")}
                    >
                      <ComponentOverrideBody
                        form={form}
                        componentName={componentName}
                        field={field}
                        rows={rows}
                        initialBlock={initialByName.get(componentName)}
                        environmentBlock={envByName.get(componentName)}
                      />
                    </CollapsibleContent>
                  </Collapsible>
                );
              })}
              {/* Orphaned override blocks: entries in form state that point
                  at component names no longer declared by the driver. We
                  still render them with a remove affordance so the operator
                  can clean them up. */}
              {rows
                .map((row, index) => ({ row, index }))
                .filter(
                  ({ row }) =>
                    !components.some((c) => c.name === row.name) && row.name,
                )
                .map(({ row, index }) => (
                  <div
                    key={`orphan-${row.name}`}
                    className="flex items-center justify-between rounded-md border border-dashed border-amber-400 bg-amber-50 px-3 py-2 dark:border-amber-800 dark:bg-amber-950/30"
                    data-testid="component-override-orphan"
                    data-component={row.name}
                  >
                    <span className="font-mono text-xs text-amber-900 dark:text-amber-200">
                      {row.name} (no longer declared by driver)
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove orphaned override ${row.name}`}
                      onClick={() => field.removeValue(index)}
                      data-testid={`component-override-orphan-remove-${row.name}`}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
            </div>
          );
        }}
      </form.Field>
    </section>
  );
}

interface ComponentOverrideBodyProps {
  form: ReactFormLike;
  componentName: string;
  field: ComponentOverridesField;
  rows: ComponentConfigInput[];
  initialBlock: ComponentConfigInput | undefined;
  environmentBlock: ComponentConfigInput | undefined;
}

function ComponentOverrideBody({
  form,
  componentName,
  field,
  rows,
  initialBlock,
  environmentBlock,
}: ComponentOverrideBodyProps) {
  // Resolve (or lazily create) the override block for this component.
  // The block's index in the form-state array is what the inner
  // `form.Field` paths bind to; the index itself never appears in the
  // diff because `config-diff.ts` keys components by name.
  const existingIndex = rows.findIndex((r) => r?.name === componentName);

  if (existingIndex < 0) {
    return (
      <div className="space-y-3">
        <p className="text-xs italic text-muted-foreground">
          No override on this component yet.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid={`component-override-add-${componentName}`}
          onClick={() => ensureComponentBlock(field, componentName)}
        >
          Add override
        </Button>
        <FutureExtensionPlaceholder />
      </div>
    );
  }

  const blockPath = `components.${existingIndex}` as const;
  const initialEnvVars = initialBlock?.envVars ?? [];
  const envEnvVars = environmentBlock?.envVars ?? [];

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Environment variables
        </Label>
        <form.Field name={`${blockPath}.envVars`} mode="array">
          {(envField: any) => {
            const envRows: EnvVarInput[] = envField.state.value ?? [];
            return (
              <div className="mt-2 space-y-2">
                {envRows.length === 0 && (
                  <p className="text-xs italic text-muted-foreground">
                    No per-component env-var overrides.
                  </p>
                )}
                {envRows.map((_row, index) => {
                  const base = `${blockPath}.envVars.${index}` as const;
                  return (
                    <div
                      key={`comp-${componentName}-env-${index}`}
                      className="grid grid-cols-[1fr_1fr_auto] items-start gap-2"
                      data-testid="component-env-var-row"
                    >
                      <form.Field name={`${base}.name`}>
                        {(f: any) => (
                          <ChangedFieldFrame
                            name={`${base}.name`}
                            form={form}
                            initial={initialEnvVars[index]?.name}
                            environment={envEnvVars[index]?.name}
                          >
                            <div className="space-y-1">
                              <Label
                                htmlFor={`comp-${componentName}-env-name-${index}`}
                                className="text-[10px] uppercase tracking-wide text-muted-foreground"
                              >
                                Name
                              </Label>
                              <Input
                                id={`comp-${componentName}-env-name-${index}`}
                                data-testid={`comp-env-name-${componentName}-${index}`}
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
                            initial={initialEnvVars[index]?.value}
                            environment={envEnvVars[index]?.value}
                          >
                            <div className="space-y-1">
                              <Label
                                htmlFor={`comp-${componentName}-env-value-${index}`}
                                className="text-[10px] uppercase tracking-wide text-muted-foreground"
                              >
                                Value
                              </Label>
                              <Input
                                id={`comp-${componentName}-env-value-${index}`}
                                data-testid={`comp-env-value-${componentName}-${index}`}
                                value={f.state.value ?? ""}
                                onChange={(e: any) =>
                                  f.handleChange(e.target.value)
                                }
                                onBlur={f.handleBlur}
                                placeholder="debug"
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
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove env var ${index + 1} on ${componentName}`}
                        onClick={() => envField.removeValue(index)}
                        data-testid={`comp-env-remove-${componentName}-${index}`}
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
                  data-testid={`comp-env-add-${componentName}`}
                  onClick={() => envField.pushValue(emptyEnvVar())}
                >
                  Add env var
                </Button>
              </div>
            );
          }}
        </form.Field>
      </div>

      <FutureExtensionPlaceholder />

      <div className="flex justify-end">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          data-testid={`component-override-remove-${componentName}`}
          onClick={() => field.removeValue(existingIndex)}
        >
          Remove override
        </Button>
      </div>
    </div>
  );
}

/**
 * Visual "room to grow" affordance (FR-013 / SC-007). Documents the
 * per-component fields that the section is structurally ready to host
 * once the GraphQL `ComponentConfigInput` surface widens — today only
 * env vars round-trip end-to-end.
 */
function FutureExtensionPlaceholder() {
  return (
    <p
      className="rounded-md border border-dashed border-border bg-muted/40 px-3 py-2 text-[11px] italic text-muted-foreground"
      data-testid="component-override-future-placeholder"
    >
      More per-component fields (CPU / memory requests &amp; limits, replicas,
      image overrides) are coming in future iterations.
    </p>
  );
}
