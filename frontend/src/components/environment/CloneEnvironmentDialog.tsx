/**
 * CloneEnvironmentDialog — the UI entry point for `cloneEnvironment`
 * (010-environment-clone, US1–US4 / FR-012).
 *
 * One dialog carries the whole clone request: the target environment name, the
 * deployment selection, the clone-time config override, and the captured-config
 * fields to clear. The mutation is asynchronous — it returns a clone *record*,
 * not a finished environment — so the dialog's job ends at "the record exists";
 * `EnvironmentClonesSection` is where the operator watches it converge.
 *
 * Three input contracts are easy to get wrong and are therefore encoded here
 * rather than left to the caller:
 *
 * 1. **`deploymentIds` is tri-state.** Omitting the argument means "every
 *    eligible deployment" (FR-003); sending `[]` is a legal, *different*
 *    request meaning "clone the environment configuration only". The
 *    `includeAll` toggle decides which of the two is sent — the array is never
 *    used as a stand-in for "no filter".
 * 2. **`configOverride` is a camelCase `UpdateEnvironmentInput`**, and a
 *    *present* field replaces the captured one wholesale. Only the keys the
 *    operator actually typed are sent; nothing is padded with explicit nulls
 *    the way the full-replacement `updateEnvironment` form does.
 * 3. **`clearConfigFields` names snake_case `EnvironmentConfig` fields** — the
 *    persisted-JSON spelling, not the GraphQL input spelling. The checkboxes
 *    are built from the source environment's own config keys, so the names can
 *    only ever be real ones.
 *
 * Cloning is ADMIN-only (FR-010): it creates an environment and reads every
 * included deployment's data, so the whole surface — trigger included — is
 * wrapped in `IfRole minimum="ADMIN"` rather than merely disabled.
 */
import { useState } from "react";
import { useForm, useStore } from "@tanstack/react-form";
import { useQueryClient } from "@tanstack/react-query";
import { z } from "zod/v4";
import { AlertCircle, Copy } from "lucide-react";

import {
  useCloneEnvironmentMutation,
  type CloneEnvironmentMutationVariables,
  type UpdateEnvironmentInput,
} from "@/generated/graphql";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import { IfRole } from "@/auth/IfRole";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tooltip } from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Deployment eligibility
// ---------------------------------------------------------------------------

/**
 * The deployment fields the picker needs, as `GetEnvironment` already selects
 * them. Declared structurally rather than as the generated query type so the
 * page can pass its own rows straight through.
 */
export interface CloneCandidateDeployment {
  id: string;
  name: string;
  internal: boolean;
  deletedAt?: string | null;
  applicationInstance?: { id: string } | null;
}

/**
 * Why a source deployment cannot be included in a clone.
 *
 * The three values mirror the backend's environment-backup eligibility rule
 * (non-tombstoned, non-internal, carrying an active application instance) —
 * clone reuses it verbatim, so an ineligible deployment is one the capture
 * would skip anyway.
 */
export type CloneIneligibleReason =
  | "tombstoned"
  | "internal"
  | "no_active_instance";

/**
 * Classify one deployment against the clone eligibility rule.
 *
 * Returns `null` when the deployment can be cloned. Order matters only for the
 * message shown: a deleted internal deployment is reported as deleted, which is
 * the more actionable half.
 */
export function cloneIneligibilityReason(
  deployment: CloneCandidateDeployment,
): CloneIneligibleReason | null {
  if (deployment.deletedAt != null) return "tombstoned";
  if (deployment.internal) return "internal";
  if (deployment.applicationInstance == null) return "no_active_instance";
  return null;
}

/** Full sentence shown in the ineligible row's tooltip. */
export function describeCloneIneligibility(
  reason: CloneIneligibleReason,
): string {
  switch (reason) {
    case "tombstoned":
      return "This deployment is deleted. A tombstoned deployment has no live data to capture, so a clone cannot include it.";
    case "internal":
      return "This is an internal deployment managed by Styrmin. Internal deployments are never part of an environment backup, so they are never cloned.";
    case "no_active_instance":
      return "This deployment has no active application instance — it was never deployed, so there is nothing to capture.";
  }
}

/** Short label shown inline next to an ineligible deployment's name. */
export function summariseCloneIneligibility(
  reason: CloneIneligibleReason,
): string {
  switch (reason) {
    case "tombstoned":
      return "deleted";
    case "internal":
      return "internal";
    case "no_active_instance":
      return "never deployed";
  }
}

// ---------------------------------------------------------------------------
// Config override parsing
// ---------------------------------------------------------------------------

/**
 * Top-level `UpdateEnvironmentInput` field names, as the GraphQL boundary
 * spells them.
 *
 * Maintained by hand against the schema (ADR-015 rejected codegen-generated
 * mapping tables for these small cardinalities). Used only to *warn*: the list
 * going stale must never block a legitimate override, and the backend is the
 * authority that answers with `VALIDATION_ERROR`.
 */
export const UPDATE_ENVIRONMENT_INPUT_FIELDS: readonly string[] = [
  "envVars",
  "ipWhitelist",
  "dedicatedIngress",
  "scheduling",
  "fqdnSuffix",
  "externalUrlScheme",
  "externalUrlPort",
  "externalDnsEndpointsType",
  "ingressClass",
  "dbSize",
  "backupTtl",
];

export interface ParsedConfigOverride {
  /** The parsed object, or `null` when the operator left the box empty. */
  value: Record<string, unknown> | null;
  /** Blocking parse/shape error, or `null` when the text is usable. */
  error: string | null;
}

/**
 * Parse the config-override textarea.
 *
 * Blank is not an error: it means "no override", and the argument is omitted
 * from the mutation entirely (sending `{}` would be a different statement —
 * a present-but-empty input).
 */
export function parseConfigOverride(text: string): ParsedConfigOverride {
  const trimmed = text.trim();
  if (trimmed.length === 0) return { value: null, error: null };

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (err) {
    return {
      value: null,
      error: `Not valid JSON: ${err instanceof Error ? err.message : "parse failed"}`,
    };
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return {
      value: null,
      error:
        "The override must be a JSON object of UpdateEnvironmentInput fields",
    };
  }

  return { value: parsed as Record<string, unknown>, error: null };
}

/**
 * Keys in a parsed override that are not known `UpdateEnvironmentInput` fields.
 *
 * Exists for one specific footgun: the CLI's `--config-override` accepts
 * snake_case *and* camelCase keys (it validates through the SDK's Pydantic
 * model, which carries aliases), while this GraphQL boundary accepts camelCase
 * only. An operator copying `{"env_vars": …}` out of the CLI docs would
 * otherwise get a bare `VALIDATION_ERROR` after a round-trip.
 */
export function unknownOverrideFields(
  override: Record<string, unknown>,
): string[] {
  return Object.keys(override).filter(
    (key) => !UPDATE_ENVIRONMENT_INPUT_FIELDS.includes(key),
  );
}

/**
 * Top-level `EnvironmentConfig` field names present on the source environment,
 * i.e. the fields it is meaningful to clear.
 *
 * `Environment.config` is the persisted Pydantic dump, so its keys are already
 * the snake_case names `clearConfigFields` expects. Null-valued keys are
 * dropped: the field is unset, so clearing it is a legal no-op with nothing to
 * show for it.
 */
export function clearableConfigFields(
  config: Record<string, unknown> | null | undefined,
): string[] {
  if (config == null) return [];
  return Object.entries(config)
    .filter(([, value]) => value != null)
    .map(([key]) => key)
    .sort();
}

// ---------------------------------------------------------------------------
// Error mapping
// ---------------------------------------------------------------------------

/**
 * Turn a rejected `cloneEnvironment` into an actionable sentence.
 *
 * Keyed on the typed `extensions.code` carried by `GraphQLOperationError`
 * (never on the message text — see the data-fetching guidelines). The server's
 * own message is appended rather than replaced: it carries the specifics the
 * code cannot (which name, which deployment ids, which unknown field).
 */
export function describeCloneMutationError(error: unknown): string {
  if (error instanceof GraphQLOperationError) {
    const detail = error.graphqlMessage;
    switch (error.code) {
      case "ALREADY_EXISTS":
        return `That environment name is already taken on this cluster — pick another. (${detail})`;
      case "NOT_FOUND":
        return `The source environment or one of the selected applications no longer exists. Close the dialog, let the page refresh, and try again. (${detail})`;
      case "ALREADY_IN_PROGRESS":
        return `Another environment-level operation (backup, restore, or a clone still capturing) is running on this environment. Wait for it to finish and retry. (${detail})`;
      case "VALIDATION_ERROR":
        return `The clone request was rejected as invalid — check the override fields and the fields marked for clearing. (${detail})`;
      case "FORBIDDEN":
        return `Cloning an environment requires the ADMIN role. (${detail})`;
      default:
        return detail;
    }
  }
  return error instanceof Error ? error.message : "Unknown error";
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

const cloneEnvironmentSchema = z
  .object({
    name: z.string().trim().min(1, "Target environment name is required"),
    includeAll: z.boolean(),
    deploymentIds: z.array(z.string()),
    configOverride: z.string(),
    clearConfigFields: z.array(z.string()),
  })
  .superRefine((data, ctx) => {
    const { error } = parseConfigOverride(data.configOverride);
    if (error) {
      ctx.addIssue({
        code: "custom",
        message: error,
        path: ["configOverride"],
      });
    }
  });

export interface CloneEnvironmentDialogProps {
  /** The source environment. */
  environmentId: string;
  environmentName: string;
  /**
   * The source environment's deployments, straight off the page's
   * `GetEnvironment` query. Ineligible entries are kept and rendered disabled
   * with a reason — an application silently missing from the picker is
   * indistinguishable from one that was never there.
   */
  deployments: readonly CloneCandidateDeployment[];
  /** The source environment's persisted config — the clear-field candidates. */
  config?: Record<string, unknown> | null;
}

/**
 * ADMIN-only dialog that submits one `cloneEnvironment` request.
 */
export function CloneEnvironmentDialog({
  environmentId,
  environmentName,
  deployments,
  config,
}: CloneEnvironmentDialogProps) {
  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const eligibleIds = deployments
    .filter((deployment) => cloneIneligibilityReason(deployment) === null)
    .map((deployment) => deployment.id);
  const clearCandidates = clearableConfigFields(config);

  // Invalidation is declared in `onSuccess`, not after `mutateAsync` in the
  // submit handler (dev/guidelines/frontend/data-fetching.md): it belongs to
  // the mutation and is the only form a component test can exercise.
  const cloneMutation = useCloneEnvironmentMutation({
    onSuccess: () => {
      // The clones list this dialog feeds.
      void queryClient.invalidateQueries({
        queryKey: ["ListEnvironmentClones"],
      });
      // The clone's first step is a fresh capture of the source, so a new
      // environment backup shows up on the Backups tab immediately.
      void queryClient.invalidateQueries({
        queryKey: ["ListEnvironmentBackups"],
      });
      // A clone creates a whole environment (and, once the capture lands, its
      // counterpart deployments) — both listings are stale from this moment.
      void queryClient.invalidateQueries({ queryKey: ["ListEnvironments"] });
    },
  });

  const form = useForm({
    defaultValues: {
      name: "",
      includeAll: true,
      deploymentIds: eligibleIds,
      configOverride: "",
      clearConfigFields: [] as string[],
    },
    validators: { onSubmit: cloneEnvironmentSchema },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      const override = parseConfigOverride(value.configOverride).value;

      const variables: CloneEnvironmentMutationVariables = {
        environmentId,
        name: value.name.trim(),
      };
      // Omitted, never `[]`: the empty array is the legal "environment
      // configuration only" request, a different thing from "all eligible".
      if (!value.includeAll) {
        variables.deploymentIds = value.deploymentIds;
      }
      if (override !== null) {
        // The operator authored this JSON and the backend is its validator —
        // an override that fails `EnvironmentConfig` validation comes back as
        // VALIDATION_ERROR and is surfaced inline. Restating the input's shape
        // in a frontend schema would only add a second place to keep in sync.
        variables.configOverride = override as UpdateEnvironmentInput;
      }
      if (value.clearConfigFields.length > 0) {
        variables.clearConfigFields = value.clearConfigFields;
      }

      try {
        await cloneMutation.mutateAsync(variables);
        form.reset();
        setOpen(false);
      } catch (err) {
        // Surfaced inline rather than swallowed: ALREADY_EXISTS,
        // ALREADY_IN_PROGRESS and VALIDATION_ERROR are the operator's answer
        // to why no clone record appeared, and the dialog stays open with the
        // inputs intact so the name can be changed and resubmitted.
        console.error("[clone-environment] mutation failed", err);
        setSubmitError(describeCloneMutationError(err));
      }
    },
  });

  const isSubmitting = useStore(form.store, (state) => state.isSubmitting);
  const includeAll = useStore(form.store, (state) => state.values.includeAll);
  const selectedIds = useStore(
    form.store,
    (state) => state.values.deploymentIds,
  );
  const overrideText = useStore(
    form.store,
    (state) => state.values.configOverride,
  );

  const parsedOverride = parseConfigOverride(overrideText);
  const unknownFields =
    parsedOverride.value === null
      ? []
      : unknownOverrideFields(parsedOverride.value);

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen);
    if (!nextOpen) {
      form.reset();
      setSubmitError(null);
    }
  }

  return (
    <IfRole minimum="ADMIN">
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogTrigger asChild>
          <Button size="sm" data-testid="clone-environment-button">
            <Copy className="h-4 w-4" />
            Clone Environment
          </Button>
        </DialogTrigger>
        <DialogContent
          className="max-h-[85vh] max-w-2xl overflow-y-auto"
          data-testid="clone-environment-dialog"
        >
          <DialogHeader>
            <DialogTitle>Clone {environmentName}</DialogTitle>
            <DialogDescription>
              Captures a fresh environment backup of {environmentName}, then
              builds a new environment on the same cluster entirely from that
              capture. The source is never modified. Application data is copied
              as of the capture, so credentials and endpoints stored{" "}
              <em>inside</em> the data come along unchanged — the override below
              only neutralises environment configuration.
            </DialogDescription>
          </DialogHeader>

          <form
            className="flex flex-col gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              event.stopPropagation();
              void form.handleSubmit();
            }}
          >
            {submitError && (
              <Alert
                variant="destructive"
                data-testid="clone-environment-error"
              >
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Clone rejected</AlertTitle>
                <AlertDescription>{submitError}</AlertDescription>
              </Alert>
            )}

            <form.Field name="name">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor="clone-name">New environment name</Label>
                  <Input
                    id="clone-name"
                    data-testid="clone-environment-name-input"
                    placeholder={`${environmentName}-rehearsal`}
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                    onBlur={field.handleBlur}
                  />
                  {field.state.meta.errors.length > 0 && (
                    <p
                      className="text-sm text-destructive"
                      data-testid="clone-environment-name-error"
                    >
                      {field.state.meta.errors[0]?.message ??
                        String(field.state.meta.errors[0])}
                    </p>
                  )}
                </div>
              )}
            </form.Field>

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">Applications</span>
              <form.Field name="includeAll">
                {(field) => (
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="clone-include-all"
                      data-testid="clone-include-all-checkbox"
                      checked={field.state.value}
                      onCheckedChange={(checked) =>
                        field.handleChange(checked === true)
                      }
                    />
                    <Label
                      htmlFor="clone-include-all"
                      className="text-[13px] font-normal"
                    >
                      Include every eligible application
                    </Label>
                  </div>
                )}
              </form.Field>

              <form.Field name="deploymentIds">
                {(field) => (
                  <div
                    className="flex flex-col gap-1 rounded-md border border-border p-3"
                    data-testid="clone-deployment-picker"
                  >
                    {deployments.length === 0 ? (
                      <p
                        className="text-xs text-muted-foreground"
                        data-testid="clone-deployment-picker-empty"
                      >
                        This environment has no applications — the clone will
                        copy its configuration only.
                      </p>
                    ) : (
                      deployments.map((deployment) => {
                        const reason = cloneIneligibilityReason(deployment);
                        const eligible = reason === null;
                        const checked = includeAll
                          ? eligible
                          : field.state.value.includes(deployment.id);
                        // Ineligible rows are always locked; eligible rows are
                        // locked while "include every eligible application"
                        // owns the selection.
                        const locked = !eligible || includeAll;
                        const row = (
                          <div
                            key={deployment.id}
                            className="flex items-center gap-2 py-0.5"
                            data-testid="clone-deployment-option"
                            data-deployment-id={deployment.id}
                            data-deployment-name={deployment.name}
                            data-eligible={eligible}
                            data-selected={checked}
                            data-ineligible-reason={reason ?? ""}
                          >
                            <Checkbox
                              id={`clone-deployment-${deployment.id}`}
                              data-testid="clone-deployment-checkbox"
                              checked={checked}
                              disabled={locked}
                              onCheckedChange={(next) => {
                                const selected = new Set(field.state.value);
                                if (next === true) selected.add(deployment.id);
                                else selected.delete(deployment.id);
                                field.handleChange(
                                  deployments
                                    .map((candidate) => candidate.id)
                                    .filter((id) => selected.has(id)),
                                );
                              }}
                            />
                            <Label
                              htmlFor={`clone-deployment-${deployment.id}`}
                              className={`text-[13px] font-normal ${
                                eligible
                                  ? "text-foreground"
                                  : "text-muted-foreground"
                              }`}
                            >
                              {deployment.name}
                            </Label>
                            {reason && (
                              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                                {summariseCloneIneligibility(reason)}
                              </span>
                            )}
                          </div>
                        );

                        // The tooltip wraps the row, not the checkbox: a
                        // disabled control does not emit the pointer events a
                        // hover tooltip needs, so hanging the hint off the
                        // checkbox would make it unreachable.
                        return reason ? (
                          <Tooltip
                            key={deployment.id}
                            content={describeCloneIneligibility(reason)}
                          >
                            {row}
                          </Tooltip>
                        ) : (
                          row
                        );
                      })
                    )}
                    {!includeAll && selectedIds.length === 0 && (
                      <p
                        className="pt-1 text-xs text-muted-foreground"
                        data-testid="clone-no-selection-note"
                      >
                        No applications selected — the clone will contain this
                        environment&apos;s configuration and no application
                        data.
                      </p>
                    )}
                  </div>
                )}
              </form.Field>
            </div>

            <form.Field name="configOverride">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor="clone-config-override">
                    Configuration override (optional)
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    A JSON <code>UpdateEnvironmentInput</code> merged over the
                    captured configuration before any cloned application starts.
                    Field names are camelCase; a field you name replaces the
                    captured one entirely.
                  </p>
                  <textarea
                    id="clone-config-override"
                    data-testid="clone-config-override-input"
                    rows={4}
                    spellCheck={false}
                    className="w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    placeholder={
                      '{ "envVars": [{ "name": "SMTP_HOST", "value": "sink.local" }] }'
                    }
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                    onBlur={field.handleBlur}
                  />
                  {parsedOverride.error && (
                    <p
                      className="text-sm text-destructive"
                      data-testid="clone-config-override-error"
                    >
                      {parsedOverride.error}
                    </p>
                  )}
                  {unknownFields.length > 0 && (
                    <p
                      className="text-xs text-warning"
                      data-testid="clone-config-override-warning"
                    >
                      Unrecognised field{unknownFields.length > 1 ? "s" : ""}:{" "}
                      {unknownFields.join(", ")}. This form takes the camelCase
                      GraphQL names (
                      {UPDATE_ENVIRONMENT_INPUT_FIELDS.join(", ")}) — the
                      CLI&apos;s snake_case spelling is not accepted here.
                    </p>
                  )}
                </div>
              )}
            </form.Field>

            <form.Field name="clearConfigFields">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <span className="text-sm font-medium">
                    Clear captured configuration fields (optional)
                  </span>
                  <p className="text-xs text-muted-foreground">
                    Removes the field from the clone&apos;s configuration
                    entirely, rather than overriding its value — for
                    production-only settings such as a real DNS integration.
                  </p>
                  <div
                    className="flex flex-col gap-1 rounded-md border border-border p-3"
                    data-testid="clone-clear-fields"
                  >
                    {clearCandidates.length === 0 ? (
                      <p
                        className="text-xs text-muted-foreground"
                        data-testid="clone-clear-fields-empty"
                      >
                        This environment has no configuration fields set, so
                        there is nothing to clear.
                      </p>
                    ) : (
                      clearCandidates.map((configField) => (
                        <div
                          key={configField}
                          className="flex items-center gap-2 py-0.5"
                          data-testid="clone-clear-field-option"
                          data-config-field={configField}
                          data-selected={field.state.value.includes(
                            configField,
                          )}
                        >
                          <Checkbox
                            id={`clone-clear-${configField}`}
                            data-testid="clone-clear-field-checkbox"
                            checked={field.state.value.includes(configField)}
                            onCheckedChange={(next) => {
                              const selected = new Set(field.state.value);
                              if (next === true) selected.add(configField);
                              else selected.delete(configField);
                              field.handleChange(
                                clearCandidates.filter((candidate) =>
                                  selected.has(candidate),
                                ),
                              );
                            }}
                          />
                          <Label
                            htmlFor={`clone-clear-${configField}`}
                            className="font-mono text-[13px] font-normal"
                          >
                            {configField}
                          </Label>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </form.Field>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                data-testid="clone-cancel-button"
                onClick={() => handleOpenChange(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                data-testid="clone-submit-button"
                disabled={isSubmitting || parsedOverride.error !== null}
              >
                {isSubmitting ? "Cloning..." : "Start Clone"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </IfRole>
  );
}
