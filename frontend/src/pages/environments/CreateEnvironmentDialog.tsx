import { useForm, useStore } from "@tanstack/react-form";
import { z } from "zod/v4";
import {
  useListClustersQuery,
  useCreateEnvironmentMutation,
} from "@/generated/graphql";
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

const createEnvironmentSchema = z
  .object({
    name: z.string().min(1, "Environment name is required"),
    clusterId: z.string().min(1, "Cluster is required"),
    ingress_class: z.string().optional(),
    db_size: z.string().optional(),
    fqdn_suffix: z.string().optional(),
    ip_whitelist: z.string().optional(),
    dedicated_ingress_enabled: z.boolean(),
    dedicated_ingress_implementation: z.string(),
    dedicated_ingress_type: z.union([
      z.enum(["ingress", "gateway"]),
      z.literal(""),
    ]),
    dedicated_ingress_service_type: z.union([
      z.enum(["LoadBalancer", "ClusterIP", "NodePort"]),
      z.literal(""),
    ]),
    dedicated_ingress_service_node_port: z.string().optional(),
    dedicated_ingress_service_host_network: z.boolean(),
  })
  .refine(
    (data) => {
      if (!data.dedicated_ingress_enabled) return true;
      if (!data.dedicated_ingress_service_node_port) return true;
      const n = Number(data.dedicated_ingress_service_node_port);
      return Number.isInteger(n) && n >= 1 && n <= 65535;
    },
    {
      message: "NodePort must be an integer between 1 and 65535",
      path: ["dedicated_ingress_service_node_port"],
    },
  )
  .refine(
    (data) => {
      if (!data.dedicated_ingress_enabled) return true;
      if (!data.dedicated_ingress_service_node_port) return true;
      return data.dedicated_ingress_service_type === "NodePort";
    },
    {
      message: "NodePort is only valid when Service Type is NodePort",
      path: ["dedicated_ingress_service_node_port"],
    },
  )
  .refine(
    (data) => {
      if (!data.dedicated_ingress_enabled) return true;
      if (!data.dedicated_ingress_service_host_network) return true;
      return !data.dedicated_ingress_service_node_port;
    },
    {
      message: "Host network mode cannot be combined with a fixed NodePort",
      path: ["dedicated_ingress_service_host_network"],
    },
  );

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
    const di: Record<string, unknown> = {};
    if (values.dedicated_ingress_implementation)
      di.implementation = values.dedicated_ingress_implementation;
    if (values.dedicated_ingress_type) di.type = values.dedicated_ingress_type;
    if (
      values.dedicated_ingress_service_type ||
      values.dedicated_ingress_service_host_network
    ) {
      const service: Record<string, unknown> = {};
      if (values.dedicated_ingress_service_type) {
        service.type = values.dedicated_ingress_service_type;
      }
      if (
        values.dedicated_ingress_service_type === "NodePort" &&
        values.dedicated_ingress_service_node_port &&
        !values.dedicated_ingress_service_host_network
      ) {
        service.node_port = Number(values.dedicated_ingress_service_node_port);
      }
      if (values.dedicated_ingress_service_host_network) {
        service.host_network = true;
      }
      di.service = service;
    }
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
  const { data: clustersData, isLoading: clustersFetching } =
    useListClustersQuery();
  const createEnvironmentMutation = useCreateEnvironmentMutation();
  const queryClient = useQueryClient();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm({
    defaultValues: {
      name: "",
      clusterId: "",
      ingress_class: "",
      db_size: "",
      fqdn_suffix: "",
      ip_whitelist: "",
      dedicated_ingress_enabled: false,
      dedicated_ingress_implementation: "",
      dedicated_ingress_type: "" as "" | "ingress" | "gateway",
      dedicated_ingress_service_type: "" as
        | ""
        | "LoadBalancer"
        | "ClusterIP"
        | "NodePort",
      dedicated_ingress_service_node_port: "",
      dedicated_ingress_service_host_network: false,
    },
    validators: {
      onSubmit: ({ value }) => {
        const result = createEnvironmentSchema.safeParse(value);
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
      const config = buildEnvironmentConfig(value);
      try {
        const data = await createEnvironmentMutation.mutateAsync({
          name: value.name,
          clusterId: value.clusterId,
          config: config ?? null,
        });
        if (data.createEnvironment) {
          queryClient.invalidateQueries({ queryKey: ["ListEnvironments"] });
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
  const dedicatedIngressServiceType = useStore(
    form.store,
    (s) => s.values.dedicated_ingress_service_type,
  );
  const dedicatedIngressServiceHostNetwork = useStore(
    form.store,
    (s) => s.values.dedicated_ingress_service_host_network,
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
          New Environment
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create Environment</DialogTitle>
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
                <Label htmlFor="env-name">Name</Label>
                <Input
                  id="env-name"
                  placeholder="production"
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

          <form.Field name="clusterId">
            {(field) => (
              <div className="space-y-2">
                <Label htmlFor="env-cluster">Cluster</Label>
                <Select
                  value={field.state.value}
                  onValueChange={field.handleChange}
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
                    <Label htmlFor="env-ingress-class">Ingress Class</Label>
                    <Input
                      id="env-ingress-class"
                      placeholder="e.g. nginx"
                      value={field.state.value}
                      onChange={(e) => field.handleChange(e.target.value)}
                      onBlur={field.handleBlur}
                    />
                  </div>
                )}
              </form.Field>

              <form.Field name="db_size">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="env-db-size">DB Size</Label>
                    <Input
                      id="env-db-size"
                      placeholder="e.g. small"
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
                    <Label htmlFor="env-fqdn-suffix">FQDN Suffix</Label>
                    <Input
                      id="env-fqdn-suffix"
                      placeholder="example.com"
                      value={field.state.value}
                      onChange={(e) => field.handleChange(e.target.value)}
                      onBlur={field.handleBlur}
                    />
                  </div>
                )}
              </form.Field>

              <form.Field name="ip_whitelist">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="env-ip-whitelist">IP Whitelist</Label>
                    <Input
                      id="env-ip-whitelist"
                      placeholder="203.0.113.0/24, 198.51.100.0/24"
                      value={field.state.value}
                      onChange={(e) => field.handleChange(e.target.value)}
                      onBlur={field.handleBlur}
                    />
                    <p className="text-xs text-muted-foreground">
                      Comma-separated CIDR ranges
                    </p>
                  </div>
                )}
              </form.Field>

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <form.Field name="dedicated_ingress_enabled">
                    {(field) => (
                      <Checkbox
                        id="env-dedicated-ingress"
                        checked={field.state.value}
                        onCheckedChange={(checked) =>
                          field.handleChange(checked === true)
                        }
                      />
                    )}
                  </form.Field>
                  <Label
                    htmlFor="env-dedicated-ingress"
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
                          <Label htmlFor="env-di-impl">Implementation</Label>
                          <Input
                            id="env-di-impl"
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
                          <Label htmlFor="env-di-type">Type</Label>
                          <select
                            id="env-di-type"
                            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                            value={field.state.value}
                            onChange={(e) =>
                              field.handleChange(
                                e.target.value as "" | "ingress" | "gateway",
                              )
                            }
                            onBlur={field.handleBlur}
                          >
                            <option value="">(default)</option>
                            <option value="ingress">ingress</option>
                            <option value="gateway">gateway</option>
                          </select>
                        </div>
                      )}
                    </form.Field>
                    <form.Field name="dedicated_ingress_service_type">
                      {(field) => (
                        <div className="space-y-2">
                          <Label htmlFor="env-di-service-type">
                            Service Type
                          </Label>
                          <select
                            id="env-di-service-type"
                            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                            value={field.state.value}
                            onChange={(e) => {
                              const next = e.target.value as
                                | ""
                                | "LoadBalancer"
                                | "ClusterIP"
                                | "NodePort";
                              field.handleChange(next);
                              if (next !== "NodePort") {
                                form.setFieldValue(
                                  "dedicated_ingress_service_node_port",
                                  "",
                                );
                              }
                            }}
                            onBlur={field.handleBlur}
                          >
                            <option value="">(default)</option>
                            <option value="LoadBalancer">LoadBalancer</option>
                            <option value="ClusterIP">ClusterIP</option>
                            <option value="NodePort">NodePort</option>
                          </select>
                        </div>
                      )}
                    </form.Field>
                    {dedicatedIngressServiceType === "NodePort" &&
                      !dedicatedIngressServiceHostNetwork && (
                        <form.Field name="dedicated_ingress_service_node_port">
                          {(field) => (
                            <div className="space-y-2">
                              <Label htmlFor="env-di-service-node-port">
                                NodePort
                              </Label>
                              <Input
                                id="env-di-service-node-port"
                                type="number"
                                min={1}
                                max={65535}
                                placeholder="e.g. 32443"
                                value={field.state.value ?? ""}
                                onChange={(e) =>
                                  field.handleChange(e.target.value)
                                }
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
                      )}
                    <form.Field name="dedicated_ingress_service_host_network">
                      {(field) => (
                        <div className="space-y-2">
                          <div className="flex items-start gap-2">
                            <Checkbox
                              id="env-di-service-host-network"
                              checked={field.state.value}
                              onCheckedChange={(checked) => {
                                const next = checked === true;
                                field.handleChange(next);
                                if (next) {
                                  form.setFieldValue(
                                    "dedicated_ingress_service_node_port",
                                    "",
                                  );
                                }
                              }}
                            />
                            <div className="space-y-1 leading-none">
                              <Label
                                htmlFor="env-di-service-host-network"
                                className="font-medium"
                              >
                                Host network mode
                              </Label>
                              <p className="text-xs text-muted-foreground">
                                Bind Traefik directly to host ports 80/443 (pod
                                runs with hostNetwork=true).
                              </p>
                            </div>
                          </div>
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
