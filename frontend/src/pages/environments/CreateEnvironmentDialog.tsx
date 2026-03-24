import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";
import {
  useListClustersQuery,
  useCreateEnvironmentMutation,
} from "@/generated/graphql";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";

const createEnvironmentSchema = z.object({
  name: z.string().min(1, "Environment name is required"),
  clusterId: z.string().min(1, "Cluster is required"),
  ingress_class: z.string().optional(),
  db_size: z.string().optional(),
  fqdn_suffix: z.string().optional(),
  ip_whitelist: z.string().optional(),
  dedicated_ingress_enabled: z.boolean(),
  dedicated_ingress_implementation: z.string(),
  dedicated_ingress_type: z.string(),
});

type CreateEnvironmentValues = z.infer<typeof createEnvironmentSchema>;

function buildEnvironmentConfig(
  values: CreateEnvironmentValues,
): Record<string, unknown> | undefined {
  const config: Record<string, unknown> = {};
  if (values.ingress_class) config.ingress_class = values.ingress_class;
  if (values.db_size) config.db_size = values.db_size;
  if (values.fqdn_suffix) config.fqdn_suffix = values.fqdn_suffix;
  if (values.ip_whitelist) {
    const list = values.ip_whitelist
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (list.length > 0) config.ip_whitelist = list;
  }
  if (values.dedicated_ingress_enabled) {
    const di: Record<string, string> = {};
    if (values.dedicated_ingress_implementation)
      di.implementation = values.dedicated_ingress_implementation;
    if (values.dedicated_ingress_type) di.type = values.dedicated_ingress_type;
    config.dedicated_ingress = di;
  }
  return Object.keys(config).length > 0 ? config : undefined;
}

export function CreateEnvironmentDialog({
  onCreated,
}: {
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [{ data: clustersData, fetching: clustersFetching }] =
    useListClustersQuery();
  const [, executeCreate] = useCreateEnvironmentMutation();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<CreateEnvironmentValues>({
    resolver: zodResolver(createEnvironmentSchema),
    defaultValues: {
      name: "",
      clusterId: "",
      ingress_class: "",
      db_size: "",
      fqdn_suffix: "",
      ip_whitelist: "",
      dedicated_ingress_enabled: false,
      dedicated_ingress_implementation: "",
      dedicated_ingress_type: "",
    },
  });

  const dedicatedIngressEnabled = watch("dedicated_ingress_enabled");

  const onSubmit = async (values: CreateEnvironmentValues) => {
    setSubmitError(null);
    const config = buildEnvironmentConfig(values);
    const result = await executeCreate({
      name: values.name,
      clusterId: values.clusterId,
      config: config ?? null,
    });

    if (result.error) {
      setSubmitError(result.error.message);
      return;
    }

    if (result.data?.createEnvironment) {
      reset();
      setAdvancedOpen(false);
      setSubmitError(null);
      setOpen(false);
      onCreated();
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
          New Environment
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create Environment</DialogTitle>
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
            <Label htmlFor="env-name">Name</Label>
            <Input
              id="env-name"
              placeholder="production"
              {...register("name")}
            />
            {errors.name && (
              <p className="text-sm text-destructive">{errors.name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="env-cluster">Cluster</Label>
            <Controller
              name="clusterId"
              control={control}
              render={({ field }) => (
                <Select
                  value={field.value}
                  onValueChange={field.onChange}
                  disabled={clustersFetching}
                >
                  <SelectTrigger>
                    <SelectValue
                      placeholder={
                        clustersFetching
                          ? "Loading clusters..."
                          : "Select a cluster"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {clustersData?.clusters.map((cluster) => (
                      <SelectItem key={cluster.id} value={cluster.id}>
                        {cluster.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.clusterId && (
              <p className="text-sm text-destructive">
                {errors.clusterId.message}
              </p>
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
                <Label htmlFor="env-ingress-class">Ingress Class</Label>
                <Input
                  id="env-ingress-class"
                  placeholder="e.g. nginx"
                  {...register("ingress_class")}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="env-db-size">DB Size</Label>
                <Input
                  id="env-db-size"
                  placeholder="e.g. small"
                  {...register("db_size")}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="env-fqdn-suffix">FQDN Suffix</Label>
                <Input
                  id="env-fqdn-suffix"
                  placeholder="example.com"
                  {...register("fqdn_suffix")}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="env-ip-whitelist">IP Whitelist</Label>
                <Input
                  id="env-ip-whitelist"
                  placeholder="203.0.113.0/24, 198.51.100.0/24"
                  {...register("ip_whitelist")}
                />
                <p className="text-xs text-muted-foreground">
                  Comma-separated CIDR ranges
                </p>
              </div>

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <Controller
                    name="dedicated_ingress_enabled"
                    control={control}
                    render={({ field }) => (
                      <Checkbox
                        id="env-dedicated-ingress"
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    )}
                  />
                  <Label
                    htmlFor="env-dedicated-ingress"
                    className="font-medium"
                  >
                    Dedicated Ingress
                  </Label>
                </div>
                {dedicatedIngressEnabled && (
                  <div className="space-y-3 ml-6">
                    <div className="space-y-2">
                      <Label htmlFor="env-di-impl">Implementation</Label>
                      <Input
                        id="env-di-impl"
                        placeholder="e.g. traefik"
                        {...register("dedicated_ingress_implementation")}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="env-di-type">Type</Label>
                      <Input
                        id="env-di-type"
                        placeholder="e.g. ingress"
                        {...register("dedicated_ingress_type")}
                      />
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
