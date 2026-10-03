// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
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
import type { SectionId } from "@/lib/configuration-types";
import {
  imageReferenceMessage,
  validateImageReference,
} from "@/lib/image-reference";
import { cn } from "@/lib/utils";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";
import { useDrawerDiff } from "../../DrawerDiffContext";

type DeploymentComponent = NonNullable<
  GetDeploymentQuery["deployment"]
>["components"][number];

// POSIX env-var name regex — mirrors `EnvVarsSection`.
const POSIX_ENV_VAR = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Inline error for an image override; empty means "no override" and is valid. */
function imageFieldError(value: unknown): string | undefined {
  if (typeof value !== "string" || value === "") return undefined;
  const error = validateImageReference(value);
  return error ? imageReferenceMessage(error.reason) : undefined;
}

/**
 * Zod schema for the per-component override list (`UpdateDeploymentInput.components`).
 *
 * The backend `ComponentConfigInput` accepts a name, an env-var list, the
 * container-override slots `command` / `args` (014-component-container-overrides),
 * and an `image` override (018-component-image-overrides). Future per-component
 * knobs (CPU/memory, replicas) are rendered as a muted "coming soon" placeholder
 * and are **not** part of this validation schema until the GraphQL surface widens.
 *
 * Rules:
 *  - `name` non-empty (driver-declared component name; backend re-validates).
 *  - `envVars[*].name` matches the POSIX env-var regex.
 *  - Per-component env-var names are unique within that block.
 *  - Per-component `name` is unique across the whole list (one block per
 *    component).
 *  - `command` / `args` are optional `string[]`. Deliberately **no** `.min(1)`:
 *    removing every row means "clear the override", which the submit boundary
 *    encodes by omitting the field entirely (omit = clear, never `[]` — see
 *    FR-007 / `componentsFormToInput`). An empty array passing the
 *    schema is fine because it never reaches the wire.
 *  - `image` is an optional image reference checked with the shared grammar
 *    (`lib/image-reference.ts`); empty is valid and submits `image: null`.
 */
export const componentOverridesSchema = z
  .array(
    z.object({
      name: z.string().min(1, "Component name is required"),
      command: z.array(z.string()).optional(),
      args: z.array(z.string()).optional(),
      image: z
        .string()
        .superRefine((value: string, ctx: any) => {
          const message = imageFieldError(value);
          if (message) ctx.addIssue({ code: "custom", message });
        })
        .optional(),
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

/**
 * Right-aligned one-line summary for a component-override trigger. Renders a
 * token per non-empty scope (env vars / command / args / image) so a component
 * with only a command/args or image override still reads sensibly. Falls back
 * to "override (empty)" when the block exists but carries no scope yet.
 */
function summariseOverrideRow(
  envVarCount: number,
  commandCount: number,
  argsCount: number,
  hasImage: boolean,
): string {
  const parts: string[] = [];
  if (envVarCount > 0) {
    parts.push(`${envVarCount} env var${envVarCount === 1 ? "" : "s"}`);
  }
  if (commandCount > 0) {
    parts.push(`command: ${commandCount}`);
  }
  if (argsCount > 0) {
    parts.push(`args: ${argsCount}`);
  }
  if (hasImage) {
    parts.push("image");
  }
  return parts.length > 0 ? parts.join(" · ") : "override (empty)";
}

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
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
 *  - Per-component env-var field array (`ComponentConfigInput.envVars`).
 *  - An "Image" input (`ComponentConfigInput.image`, 018) and the
 *    command/args editors (014).
 *  - A muted "future per-component fields (CPU / memory / replicas)
 *    coming in future iterations" line so the section has visible room to
 *    grow without a structural rewrite.
 *
 * Components without a component container get no env var editor and no
 * Image input: stored env vars render read-only and removable (FR-006).
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

  const changedCount = useDrawerDiff().entries.filter(
    (e) => e.section === anchorId,
  ).length;

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
          Components
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
                const commandCount = overrideRow?.command?.length ?? 0;
                const argsCount = overrideRow?.args?.length ?? 0;
                const summary = summariseOverrideRow(
                  envVarCount,
                  commandCount,
                  argsCount,
                  Boolean(overrideRow?.image),
                );

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
                        {hasOverride ? summary : "no override"}
                      </span>
                    </CollapsibleTrigger>
                    <CollapsibleContent
                      className={cn("border-t border-border px-3 py-3")}
                    >
                      <ComponentOverrideBody
                        form={form}
                        componentName={componentName}
                        hasContainer={Boolean(component.container)}
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
                  still render them with a remove affordance so the user
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
  /** False when the driver declares no component container for this component. */
  hasContainer: boolean;
  field: ComponentOverridesField;
  rows: ComponentConfigInput[];
  initialBlock: ComponentConfigInput | undefined;
  environmentBlock: ComponentConfigInput | undefined;
}

function ComponentOverrideBody({
  form,
  componentName,
  hasContainer,
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
  const initialCommand = initialBlock?.command ?? [];
  const envCommand = environmentBlock?.command ?? [];
  const initialArgs = initialBlock?.args ?? [];
  const envArgs = environmentBlock?.args ?? [];
  const initialImage = initialBlock?.image ?? undefined;

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Environment variables
        </Label>
        <form.Field name={`${blockPath}.envVars`} mode="array">
          {(envField: any) => {
            const envRows: EnvVarInput[] = envField.state.value ?? [];
            if (!hasContainer) {
              return (
                <ContainerlessEnvVars
                  componentName={componentName}
                  envRows={envRows}
                  onRemove={(index) => envField.removeValue(index)}
                />
              );
            }
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

      {hasContainer && (
        <form.Field
          name={`${blockPath}.image`}
          validators={{
            onChange: ({ value }: { value: unknown }) => imageFieldError(value),
          }}
        >
          {(f: any) => {
            const inputId = `comp-${componentName}-image`;
            const hintId = `${inputId}-hint`;
            const errorId = `${inputId}-error`;
            const error =
              f.state.meta.errors.length > 0
                ? String(f.state.meta.errors[0])
                : null;
            return (
              <ChangedFieldFrame
                name={`${blockPath}.image`}
                form={form}
                initial={initialImage}
                environment={environmentBlock?.image ?? undefined}
              >
                <div
                  className="space-y-1"
                  data-testid={`component-image-editor-${componentName}`}
                >
                  <Label
                    htmlFor={inputId}
                    className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    Image
                  </Label>
                  <Input
                    id={inputId}
                    data-testid={`comp-image-${componentName}`}
                    aria-label={`Image for ${componentName}`}
                    aria-describedby={error ? `${errorId} ${hintId}` : hintId}
                    aria-invalid={error ? true : undefined}
                    value={f.state.value ?? ""}
                    onChange={(e: any) =>
                      // Nothing stored: clearing returns to undefined, so typing
                      // then clearing is not a change. Otherwise "" submits null.
                      f.handleChange(
                        e.target.value === "" && initialImage === undefined
                          ? undefined
                          : e.target.value,
                      )
                    }
                    onBlur={f.handleBlur}
                    placeholder="registry.example/acme/app:{{ app.version }}"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  {error && (
                    <p
                      id={errorId}
                      data-testid={`comp-image-error-${componentName}`}
                      className="text-xs text-destructive"
                    >
                      {error}
                    </p>
                  )}
                  <p
                    id={hintId}
                    data-testid={`comp-image-hint-${componentName}`}
                    className="text-xs text-muted-foreground"
                  >
                    Use <code className="font-mono">{"{{ app.version }}"}</code>{" "}
                    to follow the application version; a literal tag pins the
                    image.
                  </p>
                </div>
              </ChangedFieldFrame>
            );
          }}
        </form.Field>
      )}

      <div data-testid={`component-command-editor-${componentName}`}>
        <Label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Command
        </Label>
        <form.Field name={`${blockPath}.command`} mode="array">
          {(commandField: any) => {
            const commandRows: string[] = commandField.state.value ?? [];
            return (
              <div className="mt-2 space-y-2">
                {commandRows.length === 0 && (
                  <p className="text-xs italic text-muted-foreground">
                    No command override.
                  </p>
                )}
                {commandRows.map((_row, index) => {
                  const itemPath = `${blockPath}.command.${index}` as const;
                  return (
                    <div
                      key={`comp-${componentName}-command-${index}`}
                      className="grid grid-cols-[1fr_auto] items-start gap-2"
                    >
                      <form.Field name={itemPath}>
                        {(f: any) => (
                          <ChangedFieldFrame
                            name={itemPath}
                            form={form}
                            initial={initialCommand[index]}
                            environment={envCommand[index]}
                          >
                            <Input
                              data-testid={`comp-command-${componentName}-${index}`}
                              value={f.state.value ?? ""}
                              onChange={(e: any) =>
                                f.handleChange(e.target.value)
                              }
                              onBlur={f.handleBlur}
                              placeholder="/bin/sh"
                              autoComplete="off"
                            />
                          </ChangedFieldFrame>
                        )}
                      </form.Field>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove command argument ${index + 1} on ${componentName}`}
                        onClick={() => commandField.removeValue(index)}
                        data-testid={`comp-command-remove-${componentName}-${index}`}
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
                  data-testid={`comp-command-add-${componentName}`}
                  onClick={() => commandField.pushValue("")}
                >
                  Add command argument
                </Button>
              </div>
            );
          }}
        </form.Field>
      </div>

      <div data-testid={`component-args-editor-${componentName}`}>
        <Label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Args
        </Label>
        <form.Field name={`${blockPath}.args`} mode="array">
          {(argsField: any) => {
            const argsRows: string[] = argsField.state.value ?? [];
            return (
              <div className="mt-2 space-y-2">
                {argsRows.length === 0 && (
                  <p className="text-xs italic text-muted-foreground">
                    No args override.
                  </p>
                )}
                {argsRows.map((_row, index) => {
                  const itemPath = `${blockPath}.args.${index}` as const;
                  return (
                    <div
                      key={`comp-${componentName}-args-${index}`}
                      className="grid grid-cols-[1fr_auto] items-start gap-2"
                    >
                      <form.Field name={itemPath}>
                        {(f: any) => (
                          <ChangedFieldFrame
                            name={itemPath}
                            form={form}
                            initial={initialArgs[index]}
                            environment={envArgs[index]}
                          >
                            <Input
                              data-testid={`comp-args-${componentName}-${index}`}
                              value={f.state.value ?? ""}
                              onChange={(e: any) =>
                                f.handleChange(e.target.value)
                              }
                              onBlur={f.handleBlur}
                              placeholder="--verbose"
                              autoComplete="off"
                            />
                          </ChangedFieldFrame>
                        )}
                      </form.Field>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove args entry ${index + 1} on ${componentName}`}
                        onClick={() => argsField.removeValue(index)}
                        data-testid={`comp-args-remove-${componentName}-${index}`}
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
                  data-testid={`comp-args-add-${componentName}`}
                  onClick={() => argsField.pushValue("")}
                >
                  Add args entry
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

interface ContainerlessEnvVarsProps {
  componentName: string;
  envRows: EnvVarInput[];
  onRemove: (index: number) => void;
}

/**
 * Env var area for a component without a component container. The backend
 * rejects new or changed values there, so stored rows are read-only and can
 * only be removed (same treatment as orphaned override blocks).
 */
function ContainerlessEnvVars({
  componentName,
  envRows,
  onRemove,
}: ContainerlessEnvVarsProps) {
  return (
    <div className="mt-2 space-y-2">
      <p
        className="text-xs italic text-muted-foreground"
        data-testid={`comp-env-no-container-${componentName}`}
      >
        The driver declares no container for this component, so env vars
        can&apos;t be applied to it.
        {envRows.length > 0 && " Stored values can only be removed."}
      </p>
      {envRows.map((row, index) => (
        <div
          key={`comp-${componentName}-env-readonly-${index}`}
          className="flex items-center justify-between gap-2 rounded-md border border-dashed border-amber-400 bg-amber-50 px-3 py-2 dark:border-amber-800 dark:bg-amber-950/30"
          data-testid="component-env-var-readonly-row"
        >
          <span className="break-all font-mono text-xs text-amber-900 dark:text-amber-200">
            {row.name}={row.value}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Remove env var ${row.name} on ${componentName}`}
            onClick={() => onRemove(index)}
            data-testid={`comp-env-remove-${componentName}-${index}`}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
    </div>
  );
}

/**
 * Visual "room to grow" affordance (FR-013 / SC-007). Documents the
 * per-component fields that the section is structurally ready to host
 * once the GraphQL `ComponentConfigInput` surface widens.
 */
function FutureExtensionPlaceholder() {
  return (
    <p
      className="rounded-md border border-dashed border-border bg-muted/40 px-3 py-2 text-[11px] italic text-muted-foreground"
      data-testid="component-override-future-placeholder"
    >
      More per-component fields (CPU / memory requests &amp; limits, replicas)
      are coming in future iterations.
    </p>
  );
}
