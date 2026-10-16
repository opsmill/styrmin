import { useEffect, useState } from "react";
import { useForm, useStore } from "@tanstack/react-form";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Pencil } from "lucide-react";
import {
  useGetClusterQuery,
  useUpdateClusterMutation,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ClusterConfigFields } from "@/components/cluster/ClusterConfigFields";
import {
  clusterConfigSchema,
  configToFormValues,
  mergeFormValuesIntoConfig,
  nothingToSave,
  sameJson,
  schemaFieldErrors,
} from "@/components/cluster/ClusterConfigFields.helpers";
import { clusterConfigToInput } from "@/lib/cluster-input";
import {
  ClusterUpdateResult,
  ClusterUpdateReview,
  type ClusterUpdateOutcome,
} from "./ClusterUpdateSummary";

type StoredConfig = Record<string, unknown>;

interface EditableCluster {
  id: string;
  name: string;
  config: StoredConfig;
}

type Step =
  | { kind: "edit" }
  | { kind: "review"; config: StoredConfig; plan: ClusterUpdateOutcome }
  | { kind: "result"; result: ClusterUpdateOutcome };

interface EditClusterFormProps {
  cluster: EditableCluster;
  confirmingDiscard: boolean;
  onRequestClose: () => void;
  onClose: () => void;
  onKeepEditing: () => void;
  onBusyChange: (busy: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
}

function EditClusterForm({
  cluster,
  confirmingDiscard,
  onRequestClose,
  onClose,
  onKeepEditing,
  onBusyChange,
  onDirtyChange,
}: EditClusterFormProps) {
  // The config the dialog opened with; values the form does not show come from it.
  const [storedConfig] = useState(() => cluster.config);
  const [initialValues] = useState(() => configToFormValues(storedConfig));
  const [step, setStep] = useState<Step>({ kind: "edit" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const updateClusterMutation = useUpdateClusterMutation();
  const queryClient = useQueryClient();

  async function update(
    config: StoredConfig,
    dryRun: boolean,
  ): Promise<ClusterUpdateOutcome | null> {
    setError(null);
    setBusy(true);
    try {
      const data = await updateClusterMutation.mutateAsync({
        clusterId: cluster.id,
        input: clusterConfigToInput(config),
        dryRun,
      });
      return data.updateCluster;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      return null;
    } finally {
      setBusy(false);
    }
  }

  const form = useForm({
    defaultValues: initialValues,
    validators: {
      onSubmit: ({ value }) => schemaFieldErrors(clusterConfigSchema, value),
    },
    onSubmit: async ({ value }) => {
      const config = mergeFormValuesIntoConfig(storedConfig, value);
      const plan = await update(config, true);
      if (plan) setStep({ kind: "review", config, plan });
    },
  });

  async function save(config: StoredConfig) {
    const result = await update(config, false);
    if (!result) return;
    await queryClient.invalidateQueries({
      queryKey: useGetClusterQuery.getKey({ clusterId: cluster.id }),
    });
    setStep({ kind: "result", result });
  }

  const values = useStore(form.store, (s) => s.values);
  const dirty = step.kind !== "result" && !sameJson(values, initialValues);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => onBusyChange(busy), [busy, onBusyChange]);

  const idle =
    step.kind === "review" &&
    nothingToSave(step.plan.cluster.config, step.config, step.plan);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (step.kind === "edit") form.handleSubmit();
      }}
      className="space-y-4"
    >
      {step.kind === "edit" && <ClusterConfigFields form={form} />}
      {step.kind === "review" && (
        <ClusterUpdateReview
          openedConfig={storedConfig}
          newConfig={step.config}
          plan={step.plan}
        />
      )}
      {step.kind === "result" && <ClusterUpdateResult result={step.result} />}

      <div className="sticky bottom-0 -mx-6 -mb-6 space-y-3 border-t bg-background px-6 pb-6 pt-3">
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {confirmingDiscard ? (
          <div
            role="alertdialog"
            aria-label="Discard your changes?"
            className="space-y-3"
          >
            <p className="text-sm">Discard your changes? Nothing was saved.</p>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onKeepEditing}>
                Keep editing
              </Button>
              <Button type="button" variant="destructive" onClick={onClose}>
                Discard
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            {step.kind === "edit" && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={onRequestClose}
                  disabled={busy}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={busy}>
                  {busy ? "Reviewing..." : "Review changes"}
                </Button>
              </>
            )}
            {step.kind === "review" && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setError(null);
                    setStep({ kind: "edit" });
                  }}
                  disabled={busy}
                >
                  Back
                </Button>
                <Button
                  type="button"
                  onClick={() => save(step.config)}
                  disabled={busy || idle}
                >
                  {busy ? "Saving..." : "Save and redeploy"}
                </Button>
              </>
            )}
            {step.kind === "result" && (
              <Button type="button" onClick={onClose}>
                Done
              </Button>
            )}
          </div>
        )}
      </div>
    </form>
  );
}

/**
 * Edit the cluster config. Saving replaces the whole config and redeploys the
 * deployments whose resolved config changes, after a review of both.
 */
export function EditClusterDialog({ cluster }: { cluster: EditableCluster }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);

  function close() {
    setOpen(false);
    setBusy(false);
    setDirty(false);
    setConfirmingDiscard(false);
  }

  // Escape, an outside click, the close button and Cancel all come here.
  function requestClose() {
    if (busy) return;
    if (dirty) setConfirmingDiscard(true);
    else close();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => (nextOpen ? setOpen(true) : requestClose())}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Pencil className="h-4 w-4 mr-1" />
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Cluster Configuration</DialogTitle>
          <DialogDescription>
            Review the changed values and the deployments to redeploy before
            saving. The database size and the backup retention are kept as they
            are, and so are the dedicated ingress service annotations and load
            balancer IP while dedicated ingress stays on.
          </DialogDescription>
        </DialogHeader>
        {open && (
          <EditClusterForm
            cluster={cluster}
            confirmingDiscard={confirmingDiscard}
            onRequestClose={requestClose}
            onClose={close}
            onKeepEditing={() => setConfirmingDiscard(false)}
            onBusyChange={setBusy}
            onDirtyChange={setDirty}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
