import { useCallback, useMemo, useRef, useState } from "react";
import { AlertDialog } from "@base-ui/react/alert-dialog";
import { Dialog } from "@base-ui/react/dialog";
import { useForm, useStore } from "@tanstack/react-form";
import { X } from "lucide-react";

import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import {
  deploymentConfigToInput,
  deploymentParametersToInput,
} from "@/lib/deployment-input";
import { diff } from "@/lib/config-diff";
import {
  DRAWER_SECTION_GROUPS,
  type DriverParameterSchema,
  type SectionId,
} from "@/lib/configuration-types";
import { cn } from "@/lib/utils";

import { ConfigDiffDialog } from "./ConfigDiffDialog";
import { DrawerFooter } from "./DrawerFooter";
import { SectionNav } from "./SectionNav";
import { DriverParametersSection } from "./sections/edit/DriverParametersSection";
import { EnvVarsSection } from "./sections/edit/EnvVarsSection";
import { IdentitySection } from "./sections/edit/IdentitySection";
import { SchedulingSection } from "./sections/edit/SchedulingSection";
import { ServiceOverridesSection } from "./sections/edit/ServiceOverridesSection";
import { ComponentOverridesSection } from "./sections/edit/ComponentOverridesSection";
// Networking and Storage & Runtime are intentionally not editable from the
// drawer today — only the Settings page read view shows them. Re-introduce
// the imports here (and add the sections back to DRAWER_SECTION_GROUPS) when
// the editing flow is restored.

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;

type Environment = Deployment["environment"];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  deployment: Deployment;
  environment: Environment;
  driverSchema: DriverParameterSchema;
}

/**
 * Right-side slide-in drawer for editing the unified deployment
 * configuration (FR-010..FR-019, FR-028, FR-030).
 *
 * Layout:
 *   ┌─ Header (deployment · env · X) ──────────────────────────┐
 *   │ ┌─ SectionNav (200px) ─┬─ Form body (scrollable) ──────┐ │
 *   │ │                       │                              │ │
 *   │ │                       │  [placeholder anchors per    │ │
 *   │ │                       │   SectionId — sections land  │ │
 *   │ │                       │   in chunks 4b/4d]           │ │
 *   │ └───────────────────────┴──────────────────────────────┘ │
 *   ├─ DrawerFooter (sticky, pending-change count + actions) ──┤
 *   └──────────────────────────────────────────────────────────┘
 *
 * Form: a single TanStack `useForm` instance for the whole drawer (R-001).
 * Initial values come from `deploymentConfigToInput(deployment.config)` with
 * the row-level `name` and `parameters` merged in. Section components in
 * later chunks will bind to sub-paths via `form.Field`.
 *
 * Close-with-dirty (FR-018, T035): clicking the X, pressing Escape, or
 * clicking the backdrop while the form has pending changes opens a nested
 * Base UI AlertDialog "Discard pending changes?" with "Keep editing"
 * (default) and "Discard" buttons. A successful Apply path (slice 4) calls
 * `forceClose()` to bypass the prompt.
 *
 * Focus management: Base UI Dialog handles the focus trap and restores focus
 * to the trigger element on close (FR-028) — no manual `useRef` plumbing
 * required.
 */
export function ConfigEditDrawer({
  open,
  onOpenChange,
  deployment,
  environment,
  driverSchema,
}: Props) {
  // After a concurrent-edit reload (FR-029), the dialog hands us a refreshed
  // deployment snapshot. That snapshot becomes the new baseline ("before"
  // side of the diff) while the operator's pending edits in the form remain
  // intact on top of it. Until reload, this is `null` and `initialValues`
  // tracks the `deployment` prop directly.
  const [rebaselineDeployment, setRebaselineDeployment] =
    useState<Deployment | null>(null);
  const baselineDeployment = rebaselineDeployment ?? deployment;

  // Snapshot the persisted state once per "open" — used as both the form's
  // initial values AND the "before" side of the diff helper that powers the
  // footer pending-change count and the section-nav change dots.
  const initialValues = useMemo<UpdateDeploymentInput>(() => {
    const base = deploymentConfigToInput(baselineDeployment.config);
    return {
      ...base,
      name: baselineDeployment.name,
      parameters: deploymentParametersToInput(baselineDeployment.parameters),
    };
  }, [
    baselineDeployment.config,
    baselineDeployment.name,
    baselineDeployment.parameters,
  ]);

  // Frozen snapshot of the persisted state at drawer-open. Unlike
  // ``initialValues``, this does NOT update on concurrent-edit reload. The
  // submit-time merge in ConfigDiffDialog uses this to decide which
  // top-level fields the operator actually edited (current != frozen)
  // vs. which ones simply changed underneath via an out-of-band write
  // (current == frozen but refreshed baseline differs). The lazy
  // ``useState`` initialiser runs once on first render and the setter is
  // intentionally discarded — the value never changes for the lifetime
  // of the open drawer.
  const [frozenInitialValues] = useState<UpdateDeploymentInput>(
    () => initialValues,
  );

  // Parent environment configuration projected through the same helper, so
  // section components can decide whether a field's `initial` value came
  // from the environment (drives the "from X (env)" annotation in
  // ChangedFieldFrame).
  const environmentValues = useMemo<UpdateDeploymentInput>(() => {
    return deploymentConfigToInput(environment.config);
  }, [environment.config]);

  // Driver-declared service names available for override. Sourced from the
  // resolved `deployedServices` list (which is the driver's declaration
  // post-reconcile); used to populate the Services section's driver-service
  // picker so operators can only override valid choices.
  const driverServiceNames = useMemo<readonly string[]>(() => {
    const rows = deployment.deployedServices ?? [];
    const seen = new Set<string>();
    for (const row of rows) {
      if (row?.driverServiceName) seen.add(row.driverServiceName);
    }
    return Array.from(seen).sort();
  }, [deployment.deployedServices]);

  const form = useForm({
    defaultValues: initialValues,
    onSubmit: () => {
      // Submission is handled by the Review & apply dialog (T042); this
      // form's onSubmit is unused for now.
    },
  });

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  // T035: close-with-dirty AlertDialog state.
  const [confirmDiscardOpen, setConfirmDiscardOpen] = useState(false);

  // T042: Review & apply confirmation dialog state.
  const [diffDialogOpen, setDiffDialogOpen] = useState(false);

  // Subscribe to the live form values so the diff dialog always shows the
  // operator's most recent edits without re-mounting on every keystroke.
  const currentValues = useStore(
    form.store,
    (s) => (s as { values: UpdateDeploymentInput }).values,
  );

  const hasPendingChanges = useCallback((): boolean => {
    const current = form.state.values as UpdateDeploymentInput;
    return diff(initialValues, current, driverSchema).hasChanges;
  }, [form, initialValues, driverSchema]);

  /**
   * Force-close bypasses the dirty-confirmation prompt. The Review & apply
   * dialog calls this after a successful mutation so the drawer unmounts
   * cleanly without re-showing the discard confirmation against pending-
   * but-now-applied changes.
   */
  const forceClose = useCallback(() => {
    setConfirmDiscardOpen(false);
    setDiffDialogOpen(false);
    onOpenChange(false);
  }, [onOpenChange]);

  const requestClose = useCallback(() => {
    if (hasPendingChanges()) {
      setConfirmDiscardOpen(true);
    } else {
      onOpenChange(false);
    }
  }, [hasPendingChanges, onOpenChange]);

  const handleDiscard = useCallback(() => {
    form.reset();
    setConfirmDiscardOpen(false);
    onOpenChange(false);
  }, [form, onOpenChange]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        requestClose();
        return;
      }
      onOpenChange(true);
    },
    [requestClose, onOpenChange],
  );

  const handleReviewApply = useCallback(() => {
    setDiffDialogOpen(true);
  }, []);

  /**
   * Concurrent-edit reload handler (FR-029). Swap the display baseline so
   * the diff dialog re-renders against the freshly-refetched deployment;
   * form values stay intact so the operator's inputs keep showing their
   * edits. The submit path (in ConfigDiffDialog) does the merge — see
   * its ``handleApply``.
   */
  const handleReloadBaseline = useCallback((refreshed: Deployment) => {
    setRebaselineDeployment(refreshed);
  }, []);

  /**
   * Dispatch a `SectionId` to the matching section component. Centralising
   * the switch here keeps the DRAWER_SECTION_GROUPS iteration in the JSX
   * focused on layout/grouping rather than per-section prop plumbing.
   *
   * Only sections currently present in `DRAWER_SECTION_GROUPS` are reachable
   * — `networking` and `storageRuntime` deliberately fall through and render
   * nothing in the drawer (their summaries still appear on the Settings tab
   * read view).
   */
  const renderSection = (sectionId: SectionId) => {
    switch (sectionId) {
      case "identity": {
        const driverVersion =
          deployment.applicationDriverVersion?.version ?? "";
        const driverName =
          deployment.applicationDriverVersion?.applicationDriver?.name ?? "";
        const driverLabel =
          driverName && driverVersion
            ? `${driverName}@${driverVersion}`
            : driverName || driverVersion;
        return (
          <IdentitySection
            key={sectionId}
            form={form}
            initial={initialValues}
            environment={environmentValues}
            anchorId={sectionId}
            driverLabel={driverLabel}
            appVersion={deployment.applicationVersion ?? ""}
          />
        );
      }
      case "envVars":
        return (
          <EnvVarsSection
            key={sectionId}
            form={form}
            initial={initialValues}
            environment={environmentValues}
            anchorId={sectionId}
          />
        );
      case "serviceOverrides":
        return (
          <ServiceOverridesSection
            key={sectionId}
            form={form}
            initial={initialValues}
            environment={environmentValues}
            driverServiceNames={driverServiceNames}
            anchorId={sectionId}
          />
        );
      case "driverParameters":
        return (
          <DriverParametersSection
            key={sectionId}
            form={form}
            initial={initialValues}
            environment={environmentValues}
            driverSchema={driverSchema}
            anchorId={sectionId}
          />
        );
      case "scheduling":
        return (
          <SchedulingSection
            key={sectionId}
            form={form}
            initial={initialValues}
            environment={environmentValues}
            anchorId={sectionId}
          />
        );
      case "componentOverrides":
        return (
          <ComponentOverridesSection
            key={sectionId}
            form={form}
            initial={initialValues}
            environment={environmentValues}
            anchorId={sectionId}
            components={deployment.components}
          />
        );
      // Networking + Storage & Runtime intentionally fall through.
      case "networking":
      case "storageRuntime":
        return null;
    }
  };

  const titleId = "config-edit-drawer-title";

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop
          className={cn(
            "fixed inset-0 z-40 bg-black/55 transition-opacity duration-200 ease-out",
            "data-[open]:opacity-100 data-[closed]:opacity-0",
          )}
        />
        <Dialog.Popup
          aria-labelledby={titleId}
          className={cn(
            "fixed right-0 top-0 z-50 flex h-screen flex-col bg-background text-foreground shadow-2xl outline-none",
            // Width: full below xl, 760px from xl up
            "w-full xl:w-[760px]",
            // Slide-in animation — 200 ms ease-out
            "transition-transform duration-200 ease-out",
            "data-[open]:translate-x-0 data-[closed]:translate-x-full",
          )}
        >
          {/* Header */}
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-6 py-4">
            <div className="flex min-w-0 flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Edit configuration
              </span>
              <Dialog.Title
                id={titleId}
                className="truncate text-base font-semibold text-foreground"
              >
                {deployment.name}{" "}
                <span className="font-normal text-muted-foreground">
                  · {environment.name}
                </span>
              </Dialog.Title>
            </div>
            <Dialog.Close
              render={
                <button
                  type="button"
                  data-testid="drawer-close-button"
                  aria-label="Close edit configuration"
                  className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              }
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </header>

          {/* Body: 2-column layout */}
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <SectionNav
              form={form}
              initialValues={initialValues}
              driverSchema={driverSchema}
              scrollContainerRef={scrollContainerRef}
            />
            <div
              ref={scrollContainerRef}
              data-testid="drawer-scroll-container"
              className="min-w-0 flex-1 overflow-y-auto px-6 py-6"
            >
              {/*
                Drawer body is grouped per DRAWER_SECTION_GROUPS so that the
                "Global settings" vs "Components" separation is visible inline
                — matching the labelled groups in SectionNav.
              */}
              <div className="flex flex-col gap-12">
                {DRAWER_SECTION_GROUPS.map((group) => (
                  <div
                    key={group.id}
                    className="flex flex-col gap-8"
                    data-drawer-group={group.id}
                  >
                    {group.label ? (
                      <h2
                        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                        data-testid={`drawer-group-label-${group.id}`}
                      >
                        {group.label}
                      </h2>
                    ) : null}
                    {group.sectionIds.map((sectionId) =>
                      renderSection(sectionId),
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <DrawerFooter
            form={form}
            initialValues={initialValues}
            driverSchema={driverSchema}
            onDiscard={() => setConfirmDiscardOpen(true)}
            onReviewApply={handleReviewApply}
          />

          {/* T035: nested Base UI AlertDialog — close-with-dirty confirmation. */}
          <AlertDialog.Root
            open={confirmDiscardOpen}
            onOpenChange={setConfirmDiscardOpen}
          >
            <AlertDialog.Portal>
              <AlertDialog.Backdrop className="fixed inset-0 z-[60] bg-black/40" />
              <AlertDialog.Popup
                data-testid="discard-confirm-dialog"
                className={cn(
                  "fixed left-1/2 top-1/2 z-[70] w-[420px] -translate-x-1/2 -translate-y-1/2",
                  "rounded-lg border border-border bg-card p-6 shadow-xl outline-none",
                )}
              >
                <AlertDialog.Title className="text-base font-semibold text-foreground">
                  Discard pending changes?
                </AlertDialog.Title>
                <AlertDialog.Description className="mt-2 text-sm text-muted-foreground">
                  You have unsaved edits in this drawer. Discarding will revert
                  every pending change to its persisted value.
                </AlertDialog.Description>
                <div className="mt-5 flex justify-end gap-2">
                  <AlertDialog.Close
                    render={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        autoFocus
                        data-testid="discard-keep-editing-button"
                      >
                        Keep editing
                      </Button>
                    }
                  />
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={handleDiscard}
                    data-testid="discard-confirm-button"
                  >
                    Discard
                  </Button>
                </div>
              </AlertDialog.Popup>
            </AlertDialog.Portal>
          </AlertDialog.Root>

          {/* T042/T043: Review & apply confirmation dialog. Rendered inside
              the drawer Popup so the Base UI focus-trap stack nests correctly
              (the dialog gets focus while open; on close, focus returns to
              the drawer's Review & apply button). */}
          <ConfigDiffDialog
            open={diffDialogOpen}
            onOpenChange={setDiffDialogOpen}
            deployment={baselineDeployment}
            initialValues={initialValues}
            frozenInitialValues={frozenInitialValues}
            currentValues={currentValues}
            driverSchema={driverSchema}
            onApplySuccess={forceClose}
            onBackToEdit={() => setDiffDialogOpen(false)}
            onReloadBaseline={handleReloadBaseline}
          />
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
