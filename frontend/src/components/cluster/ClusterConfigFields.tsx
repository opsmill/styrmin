// The create and edit dialogs own forms of different shapes that share these
// field names, so `form` is typed loosely, as in the deployment edit sections.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "@tanstack/react-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";

interface ClusterConfigFieldsProps {
  /** A TanStack Form whose values hold every `ClusterConfigFormValues` key. */
  form: any;
}

/** The cluster config fields of the create and edit cluster dialogs. */
export function ClusterConfigFields({ form }: ClusterConfigFieldsProps) {
  const dedicatedIngressEnabled = useStore(
    form.store,
    (s: any) => s.values.dedicated_ingress_enabled as boolean,
  );
  const dedicatedIngressServiceType = useStore(
    form.store,
    (s: any) => s.values.dedicated_ingress_service_type as string,
  );
  const standardStorageEnabled = useStore(
    form.store,
    (s: any) => s.values.standard_storage_enabled as boolean,
  );
  const fastStorageEnabled = useStore(
    form.store,
    (s: any) => s.values.fast_storage_enabled as boolean,
  );

  return (
    <>
      <form.Field name="ingress_class">
        {(field: any) => (
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
        {(field: any) => (
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
        {(field: any) => (
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
        {(field: any) => (
          <div className="space-y-2">
            <Label htmlFor="cluster-external-url-scheme">
              External URL Scheme
            </Label>
            <select
              id="cluster-external-url-scheme"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={field.state.value}
              onChange={(e) =>
                field.handleChange(e.target.value as "" | "http" | "https")
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
        {(field: any) => (
          <div className="space-y-2">
            <Label htmlFor="cluster-external-url-port">External URL Port</Label>
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
        {(field: any) => (
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
            {(field: any) => (
              <Checkbox
                id="cluster-dedicated-ingress"
                checked={field.state.value}
                onCheckedChange={(checked) =>
                  field.handleChange(checked === true)
                }
              />
            )}
          </form.Field>
          <Label htmlFor="cluster-dedicated-ingress" className="font-medium">
            Dedicated Ingress
          </Label>
        </div>
        {dedicatedIngressEnabled && (
          <div className="space-y-3 ml-6">
            <form.Field name="dedicated_ingress_implementation">
              {(field: any) => (
                <div className="space-y-2">
                  <Label htmlFor="cluster-di-impl">Implementation</Label>
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
              {(field: any) => (
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
              {(field: any) => (
                <div className="space-y-2">
                  <Label htmlFor="cluster-di-service-type">Service Type</Label>
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
                {(field: any) => (
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
            )}
            <form.Field name="dedicated_ingress_service_external_traffic_policy">
              {(field: any) => (
                <div className="space-y-2">
                  <Label htmlFor="cluster-di-service-etp">
                    External Traffic Policy
                  </Label>
                  <select
                    id="cluster-di-service-etp"
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    value={field.state.value}
                    onChange={(e) =>
                      field.handleChange(
                        e.target.value as "" | "Cluster" | "Local",
                      )
                    }
                    onBlur={field.handleBlur}
                  >
                    <option value="">(default)</option>
                    <option value="Cluster">Cluster</option>
                    <option value="Local">Local</option>
                  </select>
                </div>
              )}
            </form.Field>
            <div className="space-y-2">
              <Label>IP Families</Label>
              <div className="flex items-center gap-4">
                <form.Field name="dedicated_ingress_service_ip_family_ipv4">
                  {(field: any) => (
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="cluster-di-service-ipv4"
                        checked={field.state.value}
                        onCheckedChange={(checked) =>
                          field.handleChange(checked === true)
                        }
                      />
                      <Label htmlFor="cluster-di-service-ipv4">IPv4</Label>
                    </div>
                  )}
                </form.Field>
                <form.Field name="dedicated_ingress_service_ip_family_ipv6">
                  {(field: any) => (
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="cluster-di-service-ipv6"
                        checked={field.state.value}
                        onCheckedChange={(checked) =>
                          field.handleChange(checked === true)
                        }
                      />
                      <Label htmlFor="cluster-di-service-ipv6">IPv6</Label>
                    </div>
                  )}
                </form.Field>
              </div>
            </div>
            <form.Field name="dedicated_ingress_service_ip_family_policy">
              {(field: any) => (
                <div className="space-y-2">
                  <Label htmlFor="cluster-di-service-ip-family-policy">
                    IP Family Policy
                  </Label>
                  <select
                    id="cluster-di-service-ip-family-policy"
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    value={field.state.value}
                    onChange={(e) =>
                      field.handleChange(
                        e.target.value as
                          | ""
                          | "SingleStack"
                          | "PreferDualStack"
                          | "RequireDualStack",
                      )
                    }
                    onBlur={field.handleBlur}
                  >
                    <option value="">(default)</option>
                    <option value="SingleStack">SingleStack</option>
                    <option value="PreferDualStack">PreferDualStack</option>
                    <option value="RequireDualStack">RequireDualStack</option>
                  </select>
                </div>
              )}
            </form.Field>
          </div>
        )}
      </div>

      <div className="space-y-3 rounded-md border p-3">
        <div className="flex items-center gap-2">
          <form.Field name="standard_storage_enabled">
            {(field: any) => (
              <Checkbox
                id="cluster-standard-storage"
                checked={field.state.value}
                onCheckedChange={(checked) =>
                  field.handleChange(checked === true)
                }
              />
            )}
          </form.Field>
          <Label htmlFor="cluster-standard-storage" className="font-medium">
            Standard Storage
          </Label>
        </div>
        {standardStorageEnabled && (
          <div className="space-y-3 ml-6">
            <form.Field name="standard_storage_class">
              {(field: any) => (
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
            {(field: any) => (
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
              {(field: any) => (
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
    </>
  );
}
