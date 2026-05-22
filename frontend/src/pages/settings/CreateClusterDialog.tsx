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
    external_url_scheme: z.union([z.enum(["http", "https"]), z.literal("")]),
    external_url_port: z.string().optional(),
    external_dns_endpoints_type: z.union([
      z.enum(["NodeExternalIP", "ClusterIP"]),
      z.literal(""),
    ]),
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
    standard_storage_enabled: z.boolean(),
    standard_storage_class: z.string().optional(),
    fast_storage_enabled: z.boolean(),
    fast_storage_class: z.string().optional(),
  })
  .refine(
    (data) =>
      !data.standard_storage_enabled ||
      (data.standard_storage_class && data.standard_storage_class.length > 0),
    {
      message: "Storage class is required when standard storage is enabled",
      path: ["standard_storage_class"],
    },
  )
  .refine(
    (data) =>
      !data.fast_storage_enabled ||
      (data.fast_storage_class && data.fast_storage_class.length > 0),
    {
      message: "Storage class is required when fast storage is enabled",
      path: ["fast_storage_class"],
    },
  )
  .refine(
    (data) => {
      if (!data.external_url_port) return true;
      const n = Number(data.external_url_port);
      return Number.isInteger(n) && n >= 1 && n <= 65535;
    },
    {
      message: "External URL port must be an integer between 1 and 65535",
      path: ["external_url_port"],
    },
  )
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
  );

type CreateClusterValues = z.infer<typeof createClusterSchema>;

function buildClusterConfig(
  values: CreateClusterValues,
): Record<string, unknown> | undefined {
  const config: Record<string, unknown> = {};
  if (values.ingress_class) config.ingress_class = values.ingress_class;
  if (values.fqdn_suffix) config.fqdn_suffix = values.fqdn_suffix;
  if (values.runtime_class) config.runtime_class = values.runtime_class;
  if (values.external_url_scheme)
    config.external_url_scheme = values.external_url_scheme;
  if (values.external_url_port)
    config.external_url_port = Number(values.external_url_port);
  if (values.external_dns_endpoints_type)
    config.external_dns_endpoints_type = values.external_dns_endpoints_type;
  if (values.dedicated_ingress_enabled) {
    const di: Record<string, unknown> = {};
    if (values.dedicated_ingress_implementation)
      di.implementation = values.dedicated_ingress_implementation;
    if (values.dedicated_ingress_type) di.type = values.dedicated_ingress_type;
    if (values.dedicated_ingress_service_type) {
      const service: Record<string, unknown> = {
        type: values.dedicated_ingress_service_type,
      };
      if (
        values.dedicated_ingress_service_type === "NodePort" &&
        values.dedicated_ingress_service_node_port
      ) {
        service.node_port = Number(values.dedicated_ingress_service_node_port);
      }
      di.service = service;
    }
    config.dedicated_ingress = di;
  }
  if (values.standard_storage_enabled && values.standard_storage_class) {
    config.standard_storage = {
      storage_class: values.standard_storage_class,
    };
  }
  if (values.fast_storage_enabled && values.fast_storage_class) {
    config.fast_storage = {
      storage_class: values.fast_storage_class,
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
      external_url_scheme: "" as "" | "http" | "https",
      external_url_port: "",
      external_dns_endpoints_type: "" as "" | "NodeExternalIP" | "ClusterIP",
      dedicated_ingress_enabled: false,
      dedicated_ingress_implementation: "",
      dedicated_ingress_type: "" as "" | "ingress" | "gateway",
      dedicated_ingress_service_type: "" as
        | ""
        | "LoadBalancer"
        | "ClusterIP"
        | "NodePort",
      dedicated_ingress_service_node_port: "",
      standard_storage_enabled: false,
      standard_storage_class: "",
      fast_storage_enabled: false,
      fast_storage_class: "",
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
  const dedicatedIngressServiceType = useStore(
    form.store,
    (s) => s.values.dedicated_ingress_service_type,
  );
  const standardStorageEnabled = useStore(
    form.store,
    (s) => s.values.standard_storage_enabled,
  );
  const fastStorageEnabled = useStore(
    form.store,
    (s) => s.values.fast_storage_enabled,
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

              <form.Field name="external_url_scheme">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="cluster-external-url-scheme">
                      External URL Scheme
                    </Label>
                    <select
                      id="cluster-external-url-scheme"
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      value={field.state.value}
                      onChange={(e) =>
                        field.handleChange(
                          e.target.value as "" | "http" | "https",
                        )
                      }
                      onBlur={field.handleBlur}
                    >
                      <option value="">(default)</option>
                      <option value="http">http</option>
                      <option value="https">https</option>
                    </select>
                  </div>
                )}
              </form.Field>

              <form.Field name="external_url_port">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="cluster-external-url-port">
                      External URL Port
                    </Label>
                    <Input
                      id="cluster-external-url-port"
                      type="number"
                      min={1}
                      max={65535}
                      placeholder="e.g. 8080"
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

              <form.Field name="external_dns_endpoints_type">
                {(field) => (
                  <div className="space-y-2">
                    <Label htmlFor="cluster-external-dns-endpoints-type">
                      external-dns Endpoints Type
                    </Label>
                    <select
                      id="cluster-external-dns-endpoints-type"
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      value={field.state.value}
                      onChange={(e) =>
                        field.handleChange(
                          e.target.value as "" | "NodeExternalIP" | "ClusterIP",
                        )
                      }
                      onBlur={field.handleBlur}
                    >
                      <option value="">(default)</option>
                      <option value="NodeExternalIP">NodeExternalIP</option>
                      <option value="ClusterIP">ClusterIP</option>
                    </select>
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
                          <select
                            id="cluster-di-type"
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
                          <Label htmlFor="cluster-di-service-type">
                            Service Type
                          </Label>
                          <select
                            id="cluster-di-service-type"
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
                    {dedicatedIngressServiceType === "NodePort" && (
                      <form.Field name="dedicated_ingress_service_node_port">
                        {(field) => (
                          <div className="space-y-2">
                            <Label htmlFor="cluster-di-service-node-port">
                              NodePort
                            </Label>
                            <Input
                              id="cluster-di-service-node-port"
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

              <div className="space-y-3 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <form.Field name="fast_storage_enabled">
                    {(field) => (
                      <Checkbox
                        id="cluster-fast-storage"
                        checked={field.state.value}
                        onCheckedChange={(checked) =>
                          field.handleChange(checked === true)
                        }
                      />
                    )}
                  </form.Field>
                  <Label htmlFor="cluster-fast-storage" className="font-medium">
                    Fast Storage
                  </Label>
                </div>
                {fastStorageEnabled && (
                  <div className="space-y-3 ml-6">
                    <form.Field name="fast_storage_class">
                      {(field) => (
                        <div className="space-y-2">
                          <Label htmlFor="cluster-fast-sc">Storage Class</Label>
                          <Input
                            id="cluster-fast-sc"
                            placeholder="e.g. nvme-local"
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
