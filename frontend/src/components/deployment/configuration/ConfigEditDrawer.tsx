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
  SECTION_ORDER,
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
import { NetworkingSection } from "./sections/edit/NetworkingSection";
import { SchedulingSection } from "./sections/edit/SchedulingSection";
import { ServiceOverridesSection } from "./sections/edit/ServiceOverridesSection";
import { StorageRuntimeSection } from "./sections/edit/StorageRuntimeSection";
import { ComponentOverridesSection } from "./sections/edit/ComponentOverridesSection";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;

type Environment = Deployment["environment"];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  deployment: Deployment;
  environment: Environment;
  driverSchema: DriverParameterSchema;
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

  // Parent environment configuration projected through the same helper, so
  // section components can decide whether a field's `initial` value came
  // from the environment (drives the "from X (env)" annotation in
  // ChangedFieldFrame).
  const environmentValues = useMemo<UpdateDeploymentInput>(() => {
    return deploymentConfigToInput(environment.config);
  }, [environment.config]);

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
   * Concurrent-edit reload handler (FR-029). The dialog hands us a
   * freshly-refetched deployment whose persisted state differs from what
   * we saw at drawer-open time. We swap the baseline to the new
   * deployment — the form values stay untouched, so the operator's
   * pending edits now sit on top of the refreshed persisted state and
   * the diff recomputes accordingly.
   */
  const handleReloadBaseline = useCallback((refreshed: Deployment) => {
    setRebaselineDeployment(refreshed);
  }, []);

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
            "fixed right-0 top-0 z-50 flex h-screen flex-col bg-white text-slate-900 shadow-2xl outline-none",
            // Width: full below xl, 760px from xl up
            "w-full xl:w-[760px]",
            // Slide-in animation — 200 ms ease-out
            "transition-transform duration-200 ease-out",
            "data-[open]:translate-x-0 data-[closed]:translate-x-full",
          )}
        >
          {/* Header */}
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-200 px-6 py-4">
            <div className="flex min-w-0 flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                Edit configuration
              </span>
              <Dialog.Title
                id={titleId}
                className="truncate text-base font-semibold text-slate-900"
              >
                {deployment.name}{" "}
                <span className="font-normal text-slate-500">
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
                  className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
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
                Placeholder anchors so SectionNav scroll-spy works while the
                actual section components are still under construction (chunks
                4b/4d). Each anchor carries `data-section` for the observer
                and an `id` for direct linking.
              */}
              <div className="flex flex-col gap-12">
                {SECTION_ORDER.map((sectionId) => {
                  if (sectionId === "identity") {
                    const driverVersion =
                      deployment.applicationDriverVersion?.version ?? "";
                    const driverName =
                      deployment.applicationDriverVersion?.applicationDriver
                        ?.name ?? "";
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
                  if (sectionId === "scheduling") {
                    return (
                      <SchedulingSection
                        key={sectionId}
                        form={form}
                        initial={initialValues}
                        environment={environmentValues}
                        anchorId={sectionId}
                      />
                    );
                  }
                  if (sectionId === "driverParameters") {
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
                  }
                  if (sectionId === "networking") {
                    return (
                      <NetworkingSection
                        key={sectionId}
                        form={form}
                        initial={initialValues}
                        environment={environmentValues}
                        anchorId={sectionId}
                      />
                    );
                  }
                  if (sectionId === "envVars") {
                    return (
                      <EnvVarsSection
                        key={sectionId}
                        form={form}
                        initial={initialValues}
                        environment={environmentValues}
                        anchorId={sectionId}
                      />
                    );
                  }
                  if (sectionId === "storageRuntime") {
                    return (
                      <StorageRuntimeSection
                        key={sectionId}
                        form={form}
                        initial={initialValues}
                        environment={environmentValues}
                        anchorId={sectionId}
                      />
                    );
                  }
                  if (sectionId === "serviceOverrides") {
                    return (
                      <ServiceOverridesSection
                        key={sectionId}
                        form={form}
                        initial={initialValues}
                        environment={environmentValues}
                        anchorId={sectionId}
                      />
                    );
                  }
                  if (sectionId === "componentOverrides") {
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
                  }
                  return (
                    <section
                      key={sectionId}
                      data-section={sectionId}
                      id={`${sectionId}-anchor`}
                      className="scroll-mt-4"
                    >
                      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
                        {SECTION_LABELS[sectionId]}
                      </h2>
                      <p
                        className="mt-2 text-sm italic text-slate-400"
                        data-testid={`section-placeholder-${sectionId}`}
                      >
                        Section editor lands in a follow-up slice.
                      </p>
                      {/* Section content height padding so scroll-spy can resolve
                          between adjacent placeholders without snap-back. */}
                      <div className="h-32" />
                    </section>
                  );
                })}
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
                  "rounded-lg border border-slate-200 bg-white p-6 shadow-xl outline-none",
                )}
              >
                <AlertDialog.Title className="text-base font-semibold text-slate-900">
                  Discard pending changes?
                </AlertDialog.Title>
                <AlertDialog.Description className="mt-2 text-sm text-slate-600">
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
