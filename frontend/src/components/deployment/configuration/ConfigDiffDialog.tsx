import { useCallback, useMemo, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";

import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import {
  useGetDeploymentQuery,
  useUpdateDeploymentMutation,
} from "@/generated/graphql";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { diff } from "@/lib/config-diff";
import { evaluateImpact } from "@/lib/config-impact";
import {
  SECTION_ORDER,
  type DriverParameterSchema,
  type SectionId,
} from "@/lib/configuration-types";
import { impactRules } from "@/lib/impact-rules";
import {
  componentsFormToInput,
  deploymentConfigToInput,
  deploymentParametersToInput,
} from "@/lib/deployment-input";
import { cn } from "@/lib/utils";

import { formArrayEmptyEqual } from "./conflictMerge";
import { DiffEntryRow } from "./DiffEntryRow";
import { ImpactList } from "./ImpactList";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  deployment: Deployment;
  /** Snapshot of `UpdateDeploymentInput` captured when the drawer opened. */
  initialValues: UpdateDeploymentInput;
  /**
   * Frozen drawer-open snapshot that never refreshes on concurrent-edit
   * reload. Used together with {@link Props.deployment} (the rebaselined
   * baseline) to decide, at submit time, which top-level fields the
   * operator actually edited vs. which ones changed underneath via an
   * out-of-band write.
   */
  frozenInitialValues: UpdateDeploymentInput;
  /** Current edited form values from the drawer. */
  currentValues: UpdateDeploymentInput;
  driverSchema: DriverParameterSchema;
  /**
   * Called after a successful Apply. The drawer wires this to its
   * `forceClose()` helper so the drawer skips the close-with-dirty
   * AlertDialog (the edits are now persisted, not "dirty").
   */
  onApplySuccess: () => void;
  /**
   * "Back to edit" handler — close the dialog only, leaving the drawer
   * and every pending edit intact (FR-023).
   */
  onBackToEdit: () => void;
  /**
   * Called by the conflict panel's "Reload" action when the persisted
   * baseline has moved. Receives the freshly-refetched deployment so the
   * drawer can reset its `initialValues` to the new baseline while
   * preserving the operator's pending edits on top.
   */
  onReloadBaseline: (refreshed: Deployment) => void;
}

const SECTION_LABELS: Record<SectionId, string> = {
  identity: "Identity",
  driverParameters: "Driver Parameters",
  scheduling: "Scheduling",
  networking: "Networking",
  envVars: "Environment Vars",
  storageRuntime: "Storage & Runtime",
  serviceOverrides: "Service Overrides",
  componentOverrides: "Component Overrides",
};

/**
 * Review & apply confirmation dialog (FR-020..FR-025, FR-029).
 *
 * Renders the path-level diff grouped by section, the
 * `ImpactList`, and the action footer. No type-to-confirm input
 * (FR-022). On Apply:
 *
 *  1. Re-fetch the deployment and compute a "fingerprint" of the
 *     persisted state (Strategy B from research R-012 — no backend
 *     change required for v1). If the fingerprint differs from the
 *     baseline we captured at drawer open, render the
 *     `<ConflictPanel>` instead of dispatching the mutation. The
 *     operator's pending edits are preserved against the new baseline.
 *  2. If the fingerprint is unchanged, fire `useUpdateDeploymentMutation`
 *     with `currentValues`. On success, invalidate the `GetDeployment`
 *     query and call `onApplySuccess()` so the drawer closes.
 *  3. On error, stay open and surface the message in an inline alert
 *     (FR-025). Pending edits are not cleared.
 *
 * **Concurrency strategy (R-012)**: Strategy B (client-side fingerprint
 * compare) is shipped here. Strategy A (server-issued `updatedOn` stamp
 * + typed `STALE_DEPLOYMENT_WRITE` error) is captured as a follow-up in
 * `specs/011-unified-deployment-config/research.md` and `tasks.md` T077.
 * The dialog detects a moved baseline; it does NOT yet honour a typed
 * server-side stale-write error code — that wiring lands when the
 * backend exposes the stamp.
 */
export function ConfigDiffDialog({
  open,
  onOpenChange,
  deployment,
  initialValues,
  frozenInitialValues,
  currentValues,
  driverSchema,
  onApplySuccess,
  onBackToEdit,
  onReloadBaseline,
}: Props) {
  const queryClient = useQueryClient();

  // Capture the fingerprint of the deployment as we saw it at drawer-open
  // time. We deliberately compute this from the `deployment` prop (the
  // drawer's snapshot) rather than from any live query so the value is
  // stable across re-renders triggered by background refetches.
  const baselineFingerprint = useMemo(
    () => fingerprintDeployment(deployment),
    [deployment],
  );

  // Compute the diff once per `currentValues` change.
  const diffResult = useMemo(
    () => diff(initialValues, currentValues, driverSchema),
    [initialValues, currentValues, driverSchema],
  );

  const impactSummary = useMemo(
    () => evaluateImpact(diffResult, impactRules),
    [diffResult],
  );

  const grouped = useMemo(
    () => groupBySection(diffResult.entries),
    [diffResult.entries],
  );

  const updateMutation = useUpdateDeploymentMutation();
  // The conflict-detection re-fetch — only enabled while the dialog is open.
  // We pull `refetch` off this hook to drive the foreground re-fetch from the
  // Apply handler. `enabled: false` ensures we never poll in the background.
  const conflictQuery = useGetDeploymentQuery(
    { deploymentId: deployment.id },
    { enabled: false },
  );

  const [error, setError] = useState<string | null>(null);
  const [conflictDeployment, setConflictDeployment] =
    useState<Deployment | null>(null);

  const handleApply = useCallback(async () => {
    setError(null);
    // Strategy B: foreground re-fetch + fingerprint compare.
    try {
      const fresh = await conflictQuery.refetch();
      const freshDeployment = fresh.data?.deployment;
      if (!freshDeployment) {
        setError(
          "Failed to verify deployment state before applying. Please retry.",
        );
        return;
      }
      const freshFingerprint = fingerprintDeployment(freshDeployment);
      if (freshFingerprint !== baselineFingerprint) {
        setConflictDeployment(freshDeployment);
        return;
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? `Failed to verify deployment state: ${err.message}`
          : "Failed to verify deployment state.",
      );
      return;
    }

    try {
      // The backend uses full-replacement semantics
      // (services/deployment.py:302). To preserve out-of-band writes that
      // surfaced via the conflict panel, build the mutation input by
      // merging on each top-level field:
      //
      // * Operator edited (current != frozen baseline) → use ``current``.
      // * Operator untouched (current == frozen baseline) → use the value
      //   from the refreshed ``deployment`` prop, so the out-of-band write
      //   carries through the mutation instead of being clobbered.
      //
      // Doing the merge here (instead of mutating form state in the
      // drawer's reload handler) avoids any dependency on TanStack Form's
      // ``setFieldValue`` reactivity for ``mode="array"`` fields.
      const refreshedBaseline: UpdateDeploymentInput = {
        ...deploymentConfigToInput(deployment.config),
        name: deployment.name,
        parameters: deploymentParametersToInput(deployment.parameters),
      };
      const cur = currentValues as Record<string, unknown>;
      const frozen = frozenInitialValues as Record<string, unknown>;
      const refreshed = refreshedBaseline as Record<string, unknown>;
      const mergedInput: Record<string, unknown> = {};
      for (const key of new Set([
        ...Object.keys(cur),
        ...Object.keys(refreshed),
      ])) {
        const operatorEdited = !formArrayEmptyEqual(cur[key], frozen[key]);
        mergedInput[key] = operatorEdited ? cur[key] : refreshed[key];
      }

      // Submit boundary for component blocks: empty `command`/`args` are
      // omitted (FR-007, 014; the backend rejects `[]`) and an empty `image`
      // becomes `null` (018). Both mean "clear" under full replacement.
      mergedInput.components = componentsFormToInput(
        mergedInput.components as UpdateDeploymentInput["components"],
      );

      await updateMutation.mutateAsync({
        deploymentId: deployment.id,
        input: mergedInput as UpdateDeploymentInput,
      });
      queryClient.invalidateQueries({ queryKey: ["GetDeployment"] });
      onApplySuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }, [
    baselineFingerprint,
    conflictQuery,
    currentValues,
    deployment.config,
    deployment.id,
    deployment.name,
    deployment.parameters,
    frozenInitialValues,
    onApplySuccess,
    queryClient,
    updateMutation,
  ]);

  const handleReload = useCallback(() => {
    if (!conflictDeployment) return;
    onReloadBaseline(conflictDeployment);
    setConflictDeployment(null);
    setError(null);
    onOpenChange(false);
  }, [conflictDeployment, onOpenChange, onReloadBaseline]);

  const titleId = "config-diff-dialog-title";
  const noChanges = !diffResult.hasChanges;
  const disruptive = impactSummary.topSeverity === "high";
  const isApplying = updateMutation.isPending || conflictQuery.isFetching;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop
          className={cn(
            "fixed inset-0 z-[60] bg-black/50 transition-opacity duration-150",
            "data-[open]:opacity-100 data-[closed]:opacity-0",
          )}
        />
        <Dialog.Popup
          aria-labelledby={titleId}
          data-testid="config-diff-dialog"
          className={cn(
            "fixed left-1/2 top-1/2 z-[70] flex max-h-[85vh] w-[min(720px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-xl border border-border bg-card shadow-2xl outline-none",
          )}
        >
          <header
            data-testid="diff-dialog-header"
            data-disruptive={disruptive ? "true" : "false"}
            className={cn(
              "flex items-start justify-between gap-4 border-b px-6 py-4",
              disruptive
                ? "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40"
                : "border-border",
            )}
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Dialog.Title
                  id={titleId}
                  className={cn(
                    "text-base font-semibold",
                    disruptive
                      ? "text-amber-900 dark:text-amber-200"
                      : "text-foreground",
                  )}
                >
                  Review configuration changes
                </Dialog.Title>
                {disruptive && (
                  <span
                    data-testid="diff-dialog-disruptive-banner"
                    className="inline-flex items-center gap-1 rounded-full border border-amber-400 bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:border-amber-700 dark:bg-amber-950/60 dark:text-amber-200"
                  >
                    <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                    Disruptive
                  </span>
                )}
              </div>
              <p
                className={cn(
                  "mt-1 text-xs",
                  disruptive
                    ? "text-amber-900/80 dark:text-amber-200/80"
                    : "text-muted-foreground",
                )}
              >
                {deployment.name} ·{" "}
                {diffResult.entries.length === 0
                  ? "No pending changes"
                  : `${diffResult.entries.length} pending change${
                      diffResult.entries.length === 1 ? "" : "s"
                    }`}
              </p>
            </div>
            <Dialog.Close
              render={
                <button
                  type="button"
                  aria-label="Close review dialog"
                  data-testid="diff-dialog-close-button"
                  className={cn(
                    "rounded-md p-1.5 transition-colors focus:outline-none focus-visible:ring-2",
                    disruptive
                      ? "text-amber-800 hover:bg-amber-100 hover:text-amber-950 focus-visible:ring-amber-400 dark:text-amber-300 dark:hover:bg-amber-950/60 dark:hover:text-amber-100"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring",
                  )}
                />
              }
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {conflictDeployment && (
              <ConflictBanner pendingCount={diffResult.entries.length} />
            )}
            {error && (
              <Alert
                variant="destructive"
                data-testid="diff-dialog-error"
                className="mb-4"
              >
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {noChanges ? (
              <p
                data-testid="diff-dialog-empty"
                className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground"
              >
                No pending changes. Close this dialog and edit a field to enable
                Apply.
              </p>
            ) : (
              <div className="flex flex-col gap-6">
                <section
                  aria-label="Diff"
                  data-testid="diff-dialog-diff-section"
                >
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Diff
                  </h3>
                  <div className="flex flex-col gap-4">
                    {SECTION_ORDER.filter(
                      (id) => grouped[id] && grouped[id].length > 0,
                    ).map((id) => (
                      <div
                        key={id}
                        data-testid={`diff-section-${id}`}
                        className="flex flex-col gap-2"
                      >
                        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          {SECTION_LABELS[id]}
                        </h4>
                        <div className="flex flex-col gap-1.5">
                          {grouped[id]?.map((entry) => (
                            <DiffEntryRow
                              key={`${entry.path}-${entry.kind}`}
                              entry={entry}
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                {impactSummary.entries.length > 0 && (
                  <section
                    aria-label="Impact"
                    data-testid="diff-dialog-impact-section"
                  >
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Impact
                    </h3>
                    <ImpactList summary={impactSummary} />
                  </section>
                )}
              </div>
            )}
          </div>

          <footer className="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onBackToEdit}
              disabled={isApplying}
              data-testid="diff-dialog-back-button"
            >
              ← Back to edit
            </Button>
            {conflictDeployment ? (
              <Button
                type="button"
                size="sm"
                onClick={handleReload}
                data-testid="diff-dialog-reload-button"
              >
                Reload
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  void handleApply();
                }}
                disabled={noChanges || isApplying}
                data-testid="diff-dialog-apply-button"
                className={cn(
                  disruptive &&
                    "bg-amber-600 text-white hover:bg-amber-700 focus-visible:ring-amber-400",
                )}
              >
                {isApplying ? "Applying…" : "Apply"}
              </Button>
            )}
          </footer>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Inline banner shown above the diff when a concurrent-edit conflict has
 * been detected. The diff and impact list stay visible underneath so the
 * operator retains visual context of the pending edits while they decide
 * whether to reload — the standing UX rule is "never hide what the
 * operator was about to apply" (US2 review feedback).
 *
 * Actions (Reload / Back to edit) live in the dialog footer alongside
 * the regular Apply path so focus management and button placement stay
 * consistent across both states.
 */
function ConflictBanner({ pendingCount }: { pendingCount: number }) {
  return (
    <div
      data-testid="diff-dialog-conflict-panel"
      className="mb-4 flex items-start gap-3 rounded-md border border-amber-400 bg-amber-50 px-4 py-3 text-amber-900 dark:border-amber-500/60 dark:bg-amber-950/30 dark:text-amber-200"
    >
      <AlertTriangle
        className="mt-0.5 h-5 w-5 shrink-0 text-amber-700 dark:text-amber-300"
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="text-sm font-semibold">
          This deployment was modified while you were editing
        </p>
        <p className="mt-1 text-xs text-amber-900/80 dark:text-amber-200/80">
          Another client saved changes since you opened the drawer. We&apos;ve
          held your {pendingCount} pending{" "}
          {pendingCount === 1 ? "edit" : "edits"} below — click{" "}
          <span className="font-semibold">Reload</span> to merge them against
          the latest persisted state.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a stable fingerprint of a deployment's persisted state for
 * Strategy-B concurrency detection (research R-012).
 *
 * We hash the same fields the operator can edit: `name`, `parameters`,
 * and `config` (which carries every editable section). If any of those
 * have moved on the server between drawer-open time and Apply time, the
 * fingerprint changes and we surface the conflict panel.
 *
 * Keys are sorted before serialisation via {@link canonicalStringify}: a
 * resolver field reorder or a different fetch path must not produce a
 * spurious fingerprint mismatch.
 */
function fingerprintDeployment(deployment: Deployment): string {
  return canonicalStringify({
    name: deployment.name,
    parameters: deploymentParametersToInput(deployment.parameters),
    config: deploymentConfigToInput(deployment.config),
  });
}

/**
 * `JSON.stringify` with object keys sorted at every depth so two structurally
 * equal values always produce the same string regardless of insertion order.
 * Arrays keep their order — list semantics matter to the operator.
 */
function canonicalStringify(value: unknown): string {
  return JSON.stringify(value, (_key, val) => {
    if (val === null || typeof val !== "object" || Array.isArray(val)) {
      return val;
    }
    const obj = val as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    for (const k of Object.keys(obj).sort()) {
      sorted[k] = obj[k];
    }
    return sorted;
  });
}

function groupBySection(
  entries: ReturnType<typeof diff>["entries"],
): Partial<Record<SectionId, typeof entries>> {
  const out: Partial<Record<SectionId, typeof entries>> = {};
  for (const entry of entries) {
    const existing = out[entry.section];
    if (existing) {
      existing.push(entry);
    } else {
      out[entry.section] = [entry];
    }
  }
  return out;
}
