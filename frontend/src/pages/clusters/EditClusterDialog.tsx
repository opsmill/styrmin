import { useState } from "react";
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
  schemaFieldErrors,
} from "@/components/cluster/ClusterConfigFields.helpers";
import { clusterConfigToInput } from "@/lib/cluster-input";

interface EditableCluster {
  id: string;
  name: string;
  config: Record<string, unknown>;
}

interface EditClusterFormProps {
  cluster: EditableCluster;
  onCancel: () => void;
  onSaved: () => void;
}

function EditClusterForm({ cluster, onCancel, onSaved }: EditClusterFormProps) {
  // The config the dialog opened with; values the form does not show come from it.
  const [storedConfig] = useState(() => cluster.config);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const updateClusterMutation = useUpdateClusterMutation();
  const queryClient = useQueryClient();

  const form = useForm({
    defaultValues: configToFormValues(storedConfig),
    validators: {
      onSubmit: ({ value }) => schemaFieldErrors(clusterConfigSchema, value),
    },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      try {
        const config = mergeFormValuesIntoConfig(storedConfig, value);
        await updateClusterMutation.mutateAsync({
          clusterId: cluster.id,
          input: clusterConfigToInput(config),
        });
        await queryClient.invalidateQueries({
          queryKey: useGetClusterQuery.getKey({ clusterId: cluster.id }),
        });
        onSaved();
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : "Unknown error");
      }
    },
  });

  const isSubmitting = useStore(form.store, (s) => s.isSubmitting);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        e.stopPropagation();
        form.handleSubmit();
      }}
      className="space-y-4"
    >
      {submitError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      )}

      <ClusterConfigFields form={form} />

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Saving..." : "Save"}
        </Button>
      </div>
    </form>
  );
}

/**
 * Edit the cluster config. Saving replaces the whole config and redeploys the
 * deployments whose resolved config changes; values the form does not show
 * are kept.
 */
export function EditClusterDialog({ cluster }: { cluster: EditableCluster }) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
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
            Saving redeploys every deployment whose configuration changes.
            Scheduling, node selector, database size, backup retention and the
            dedicated ingress service annotations and load balancer IP are kept
            as they are.
          </DialogDescription>
        </DialogHeader>
        {open && (
          <EditClusterForm
            cluster={cluster}
            onCancel={() => setOpen(false)}
            onSaved={() => setOpen(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
