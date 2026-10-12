import { useForm, useStore } from "@tanstack/react-form";
import { z } from "zod/v4";
import { useCreateClusterMutation } from "@/generated/graphql";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";
import { ClusterConfigFields } from "@/components/cluster/ClusterConfigFields";
import {
  EMPTY_CLUSTER_CONFIG_VALUES,
  clusterConfigShape,
  formValuesToConfig,
  refineClusterConfig,
  schemaFieldErrors,
} from "@/components/cluster/ClusterConfigFields.helpers";

const createClusterSchema = z
  .object({
    name: z.string().min(1, "Cluster name is required"),
    ...clusterConfigShape,
  })
  .superRefine(refineClusterConfig);

export function CreateClusterDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const createClusterMutation = useCreateClusterMutation();
  const queryClient = useQueryClient();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm({
    defaultValues: { name: "default", ...EMPTY_CLUSTER_CONFIG_VALUES },
    validators: {
      onSubmit: ({ value }) => schemaFieldErrors(createClusterSchema, value),
    },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      const config = formValuesToConfig(value);
      try {
        const data = await createClusterMutation.mutateAsync({
          name: value.name,
          config: Object.keys(config).length > 0 ? config : null,
        });
        if (data.createCluster) {
          queryClient.invalidateQueries({ queryKey: ["ListClusters"] });
          form.reset();
          setAdvancedOpen(false);
          setSubmitError(null);
          setOpen(false);
          onCreated();
        }
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : "Unknown error");
      }
    },
  });

  const isSubmitting = useStore(form.store, (s) => s.isSubmitting);

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      form.reset();
      setAdvancedOpen(false);
      setSubmitError(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="h-4 w-4 mr-1" />
          New Cluster
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create Cluster</DialogTitle>
        </DialogHeader>
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

          <form.Field name="name">
            {(field) => (
              <div className="space-y-2">
                <Label htmlFor="cluster-name">Name</Label>
                <Input
                  id="cluster-name"
                  placeholder="my-cluster"
                  value={field.state.value}
                  onChange={(e) => field.handleChange(e.target.value)}
                  onBlur={field.handleBlur}
                />
                {field.state.meta.errors.length > 0 && (
                  <p className="text-sm text-destructive">
                    {field.state.meta.errors[0]?.toString()}
                  </p>
                )}
              </div>
            )}
          </form.Field>

          <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <ChevronRight
                  className={`h-4 w-4 transition-transform ${advancedOpen ? "rotate-90" : ""}`}
                />
                Advanced Configuration
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-4 pt-3">
              <ClusterConfigFields form={form} />
            </CollapsibleContent>
          </Collapsible>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
