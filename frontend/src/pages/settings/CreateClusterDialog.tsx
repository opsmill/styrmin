import { useForm, useStore } from "@tanstack/react-form";
import { z } from "zod/v4";
import { useCreateClusterMutation } from "@/generated/graphql";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
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

const createClusterSchema = z
  .object({
    name: z.string().min(1, "Cluster name is required"),
    ingress_class: z.string().optional(),
    fqdn_suffix: z.string().optional(),
    runtime_class: z.string().optional(),
    available_runtime_classes: z.string().optional(),
    dedicated_ingress_enabled: z.boolean(),
    dedicated_ingress_implementation: z.string(),
    dedicated_ingress_type: z.string(),
    standard_storage_enabled: z.boolean(),
    standard_storage_class: z.string().optional(),
  })
  .refine(
    (data) =>
      !data.standard_storage_enabled ||
      (data.standard_storage_class && data.standard_storage_class.length > 0),
    {
      message: "Storage class is required when standard storage is enabled",
      path: ["standard_storage_class"],
    },
  );

type CreateClusterValues = z.infer<typeof createClusterSchema>;

function buildClusterConfig(
  values: CreateClusterValues,
): Record<string, unknown> | undefined {
  const config: Record<string, unknown> = {};
  if (values.ingress_class) config.ingress_class = values.ingress_class;
  if (values.fqdn_suffix) config.fqdn_suffix = values.fqdn_suffix;
  if (values.runtime_class) config.runtime_class = values.runtime_class;
  if (values.available_runtime_classes) {
    const classes = values.available_runtime_classes
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (classes.length > 0) config.available_runtime_classes = classes;
  }
  if (values.dedicated_ingress_enabled) {
    const di: Record<string, string> = {};
    if (values.dedicated_ingress_implementation)
      di.implementation = values.dedicated_ingress_implementation;
    if (values.dedicated_ingress_type) di.type = values.dedicated_ingress_type;
    config.dedicated_ingress = di;
  }
  if (values.standard_storage_enabled && values.standard_storage_class) {
    config.standard_storage = {
      storage_class: values.standard_storage_class,
    };
  }
  return Object.keys(config).length > 0 ? config : undefined;
}

export function CreateClusterDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const createClusterMutation = useCreateClusterMutation();
  const queryClient = useQueryClient();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm({
    defaultValues: {
      name: "default",
      ingress_class: "",
      fqdn_suffix: "",
      runtime_class: "",
      available_runtime_classes: "",
      dedicated_ingress_enabled: false,
      dedicated_ingress_implementation: "",
      dedicated_ingress_type: "",
      standard_storage_enabled: false,
      standard_storage_class: "",
    },
    validators: {
      onSubmit: ({ value }) => {
        const result = createClusterSchema.safeParse(value);
        if (result.success) return undefined;
        const fieldErrors: Record<string, string> = {};
        for (const issue of result.error.issues) {
          const path = issue.path.join(".");
          if (path) fieldErrors[path] = issue.message;
        }
        return { fields: fieldErrors };
      },
    },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      const config = buildClusterConfig(value);
      try {
        const data = await createClusterMutation.mutateAsync({
          name: value.name,
          config: config ?? null,
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
  const dedicatedIngressEnabled = useStore(
    form.store,
    (s) => s.values.dedicated_ingress_enabled,
  );
  const standardStorageEnabled = useStore(
    form.store,
    (s) => s.values.standard_storage_enabled,
  );

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
              <form.Field name="ingress_class">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="cluster-ingress-class">Ingress Class</Label>
                    <Input
                      id="cluster-ingress-class"
                      placeholder="e.g. nginx"
                      value={field.state.value}
                      onChange={(e) => field.handleChange(e.target.value)}
                      onBlur={field.handleBlur}
                    />
                  </div>
                )}
              </form.Field>

              <form.Field name="fqdn_suffix">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="cluster-fqdn-suffix">FQDN Suffix</Label>
                    <Input
                      id="cluster-fqdn-suffix"
                      placeholder="example.com"
                      value={field.state.value}
                      onChange={(e) => field.handleChange(e.target.value)}
                      onBlur={field.handleBlur}
                    />
                  </div>
                )}
              </form.Field>

              <form.Field name="runtime_class">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="cluster-runtime-class">Runtime Class</Label>
                    <Input
                      id="cluster-runtime-class"
                      placeholder="e.g. default"
                      value={field.state.value}
                      onChange={(e) => field.handleChange(e.target.value)}
                      onBlur={field.handleBlur}
                    />
                  </div>
                )}
              </form.Field>

              <form.Field name="available_runtime_classes">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="cluster-available-runtime-classes">
                      Available Runtime Classes
                    </Label>
                    <Input
                      id="cluster-available-runtime-classes"
                      placeholder="comma-separated, e.g. kata, gvisor"
                      value={field.state.value}
                      onChange={(e) => field.handleChange(e.target.value)}
                      onBlur={field.handleBlur}
                    />
                  </div>
                )}
              </form.Field>

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <form.Field name="dedicated_ingress_enabled">
                    {(field) => (
                      <Checkbox
                        id="cluster-dedicated-ingress"
                        checked={field.state.value}
                        onCheckedChange={(checked) =>
                          field.handleChange(checked === true)
                        }
                      />
                    )}
                  </form.Field>
                  <Label
                    htmlFor="cluster-dedicated-ingress"
                    className="font-medium"
                  >
                    Dedicated Ingress
                  </Label>
                </div>
                {dedicatedIngressEnabled && (
                  <div className="space-y-3 ml-6">
                    <form.Field name="dedicated_ingress_implementation">
                      {(field) => (
                        <div className="space-y-2">
                          <Label htmlFor="cluster-di-impl">
                            Implementation
                          </Label>
                          <Input
                            id="cluster-di-impl"
                            placeholder="e.g. traefik"
                            value={field.state.value}
                            onChange={(e) => field.handleChange(e.target.value)}
                            onBlur={field.handleBlur}
                          />
                        </div>
                      )}
                    </form.Field>
                    <form.Field name="dedicated_ingress_type">
                      {(field) => (
                        <div className="space-y-2">
                          <Label htmlFor="cluster-di-type">Type</Label>
                          <Input
                            id="cluster-di-type"
                            placeholder="e.g. ingress"
                            value={field.state.value}
                            onChange={(e) => field.handleChange(e.target.value)}
                            onBlur={field.handleBlur}
                          />
                        </div>
                      )}
                    </form.Field>
                  </div>
                )}
              </div>

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <form.Field name="standard_storage_enabled">
                    {(field) => (
                      <Checkbox
                        id="cluster-standard-storage"
                        checked={field.state.value}
                        onCheckedChange={(checked) =>
                          field.handleChange(checked === true)
                        }
                      />
                    )}
                  </form.Field>
                  <Label
                    htmlFor="cluster-standard-storage"
                    className="font-medium"
                  >
                    Standard Storage
                  </Label>
                </div>
                {standardStorageEnabled && (
                  <div className="space-y-3 ml-6">
                    <form.Field name="standard_storage_class">
                      {(field) => (
                        <div className="space-y-2">
                          <Label htmlFor="cluster-sc">Storage Class</Label>
                          <Input
                            id="cluster-sc"
                            placeholder="e.g. ebs-gp3"
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
                  </div>
                )}
              </div>
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
