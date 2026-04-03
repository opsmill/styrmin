import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
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

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<CreateClusterValues>({
    resolver: zodResolver(createClusterSchema),
    defaultValues: {
      name: "default",
      ingress_class: "",
      fqdn_suffix: "",
      runtime_class: "",
      dedicated_ingress_enabled: false,
      dedicated_ingress_implementation: "",
      dedicated_ingress_type: "",
      standard_storage_enabled: false,
      standard_storage_class: "",
    },
  });

  const dedicatedIngressEnabled = watch("dedicated_ingress_enabled");
  const standardStorageEnabled = watch("standard_storage_enabled");

  const onSubmit = async (values: CreateClusterValues) => {
    setSubmitError(null);
    const config = buildClusterConfig(values);
    try {
      const data = await createClusterMutation.mutateAsync({
        name: values.name,
        config: config ?? null,
      });
      if (data.createCluster) {
        queryClient.invalidateQueries({ queryKey: ["ListClusters"] });
        reset();
        setAdvancedOpen(false);
        setSubmitError(null);
        setOpen(false);
        onCreated();
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      reset();
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
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {submitError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{submitError}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="cluster-name">Name</Label>
            <Input
              id="cluster-name"
              placeholder="my-cluster"
              {...register("name")}
            />
            {errors.name && (
              <p className="text-sm text-destructive">{errors.name.message}</p>
            )}
          </div>

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
              <div className="space-y-2">
                <Label htmlFor="cluster-ingress-class">Ingress Class</Label>
                <Input
                  id="cluster-ingress-class"
                  placeholder="e.g. nginx"
                  {...register("ingress_class")}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cluster-fqdn-suffix">FQDN Suffix</Label>
                <Input
                  id="cluster-fqdn-suffix"
                  placeholder="example.com"
                  {...register("fqdn_suffix")}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cluster-runtime-class">Runtime Class</Label>
                <Input
                  id="cluster-runtime-class"
                  placeholder="e.g. default"
                  {...register("runtime_class")}
                />
              </div>

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <Controller
                    name="dedicated_ingress_enabled"
                    control={control}
                    render={({ field }) => (
                      <Checkbox
                        id="cluster-dedicated-ingress"
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    )}
                  />
                  <Label
                    htmlFor="cluster-dedicated-ingress"
                    className="font-medium"
                  >
                    Dedicated Ingress
                  </Label>
                </div>
                {dedicatedIngressEnabled && (
                  <div className="space-y-3 ml-6">
                    <div className="space-y-2">
                      <Label htmlFor="cluster-di-impl">Implementation</Label>
                      <Input
                        id="cluster-di-impl"
                        placeholder="e.g. traefik"
                        {...register("dedicated_ingress_implementation")}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="cluster-di-type">Type</Label>
                      <Input
                        id="cluster-di-type"
                        placeholder="e.g. ingress"
                        {...register("dedicated_ingress_type")}
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <Controller
                    name="standard_storage_enabled"
                    control={control}
                    render={({ field }) => (
                      <Checkbox
                        id="cluster-standard-storage"
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    )}
                  />
                  <Label
                    htmlFor="cluster-standard-storage"
                    className="font-medium"
                  >
                    Standard Storage
                  </Label>
                </div>
                {standardStorageEnabled && (
                  <div className="space-y-3 ml-6">
                    <div className="space-y-2">
                      <Label htmlFor="cluster-sc">Storage Class</Label>
                      <Input
                        id="cluster-sc"
                        placeholder="e.g. ebs-gp3"
                        {...register("standard_storage_class")}
                      />
                      {errors.standard_storage_class && (
                        <p className="text-sm text-destructive">
                          {errors.standard_storage_class.message}
                        </p>
                      )}
                    </div>
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
