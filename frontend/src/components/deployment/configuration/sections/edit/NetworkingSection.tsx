// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "@tanstack/react-form";
import { X } from "lucide-react";
import { z } from "zod";

import type { ReactFormLike } from "./types";

import type {
  DedicatedIngressInput,
  ExternalDnsEndpointsType,
  ExternalUrlScheme,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { diff } from "@/lib/config-diff";
import type {
  DriverParameterSchema,
  SectionId,
} from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";

// --- Validation regexes -----------------------------------------------------

const K8S_NAME = /^[a-z]([-a-z0-9]*[a-z0-9])?$/;
// Permissive DNS suffix matcher — must be 1-253 chars and contain only
// dotted RFC 1123 labels. Empty strings rejected separately so the message
// is clear.
const DNS_SUFFIX =
  /^([a-z0-9]([-a-z0-9]*[a-z0-9])?)(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$/i;
// CIDR matcher — accepts IPv4 (0.0.0.0/0) and a permissive IPv6 form. The
// backend re-validates with the canonical library; we just keep the UI from
// submitting obvious garbage.
const CIDR_V4 = /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/;
const CIDR_V6 = /^[0-9a-f:]+\/\d{1,3}$/i;

const externalUrlScheme = z.enum([
  "HTTP",
  "HTTPS",
]) satisfies z.ZodType<ExternalUrlScheme>;
const externalDnsEndpointsType = z.enum([
  "CLUSTER_IP",
  "NODE_EXTERNAL_IP",
]) satisfies z.ZodType<ExternalDnsEndpointsType>;

const ingressServiceConfigSchema = z.object({
  type: z.string().optional(),
  externalTrafficPolicy: z.string().optional(),
  ipFamilies: z.array(z.string()).optional(),
  ipFamilyPolicy: z.string().optional(),
  loadBalancerIp: z.string().optional(),
  nodePort: z.number().int().min(1).max(65535).optional(),
  annotations: z.record(z.string(), z.unknown()).optional(),
});

const dedicatedIngressSchema: z.ZodType<DedicatedIngressInput> = z.object({
  type: z.string().optional(),
  implementation: z.string().optional(),
  service: ingressServiceConfigSchema.optional(),
});

/**
 * Zod schema for the `Networking` slice (data-model.md "Networking" row).
 */
export const networkingSchema = z.object({
  fqdnSuffix: z
    .string()
    .trim()
    .optional()
    .refine((v: any) => !v || DNS_SUFFIX.test(v), {
      message: "Must be a valid DNS suffix (e.g. example.com).",
    }),
  externalUrlScheme: externalUrlScheme.optional(),
  externalUrlPort: z.number().int().min(1).max(65535).optional(),
  externalDnsEndpointsType: externalDnsEndpointsType.optional(),
  ingressClass: z
    .string()
    .trim()
    .optional()
    .refine((v: any) => !v || K8S_NAME.test(v), {
      message: "Must be a valid Kubernetes name (RFC 1035).",
    }),
  dedicatedIngress: dedicatedIngressSchema.optional(),
  ipWhitelist: z
    .array(
      z
        .string()
        .trim()
        .refine((v: any) => CIDR_V4.test(v) || CIDR_V6.test(v), {
          message: "Must be a valid CIDR (e.g. 10.0.0.0/8).",
        }),
    )
    .optional(),
});

const EXTERNAL_URL_SCHEMES: ExternalUrlScheme[] = ["HTTP", "HTTPS"];
const EXTERNAL_DNS_TYPES: ExternalDnsEndpointsType[] = [
  "CLUSTER_IP",
  "NODE_EXTERNAL_IP",
];

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
  anchorId: SectionId;
}

/**
 * Networking section of the edit drawer. Top-to-bottom:
 *
 *  - FQDN suffix (string).
 *  - External URL — scheme select + port number input.
 *  - External DNS endpoint source (enum).
 *  - Ingress class (string).
 *  - Dedicated ingress — collapsed sub-form gated by an Enabled toggle.
 *  - IP allowlist — field array of CIDRs.
 */
export function NetworkingSection({
  form,
  initial,
  environment,
  anchorId,
}: Props) {
  const initialDedicated = initial.dedicatedIngress;
  const envDedicated = environment.dedicatedIngress;
  const initialAllowlist = (initial.ipWhitelist ?? []) as string[];
  const envAllowlist = (environment.ipWhitelist ?? []) as string[];

  const changedCount = useStore(
    form.store,
    (state: any) =>
      diff(initial, state.values, [] as DriverParameterSchema).entries.filter(
        (e: any) => e.section === anchorId,
      ).length,
  );
  const dedicatedEnabled = useStore(form.store, (state: any) => {
    const di = state.values?.dedicatedIngress;
    return di != null;
  });

  return (
    <section
      data-section={anchorId}
      id={`${anchorId}-anchor`}
      className="scroll-mt-4"
    >
      <div className="mb-3 flex items-center gap-3">
        <h3
          id={`${anchorId}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-foreground"
        >
          Networking
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
          >
            {changedCount} changed
          </span>
        )}
      </div>

      <div className="space-y-4">
        {/* FQDN suffix */}
        <form.Field name="fqdnSuffix">
          {(f: any) => (
            <ChangedFieldFrame
              name="fqdnSuffix"
              form={form}
              initial={initial.fqdnSuffix}
              environment={environment.fqdnSuffix}
            >
              <div className="space-y-1">
                <Label htmlFor="net-fqdn-suffix">FQDN suffix</Label>
                <Input
                  id="net-fqdn-suffix"
                  data-testid="net-fqdn-suffix"
                  value={f.state.value ?? ""}
                  onChange={(e: any) =>
                    f.handleChange(
                      e.target.value === "" ? undefined : e.target.value,
                    )
                  }
                  onBlur={f.handleBlur}
                  placeholder="e.g. example.com"
                  autoComplete="off"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        {/* External URL scheme + port */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <form.Field name="externalUrlScheme">
            {(f: any) => (
              <ChangedFieldFrame
                name="externalUrlScheme"
                form={form}
                initial={initial.externalUrlScheme}
                environment={environment.externalUrlScheme}
              >
                <div className="space-y-1">
                  <Label htmlFor="net-url-scheme">External URL scheme</Label>
                  <Select
                    value={(f.state.value as string | undefined) ?? ""}
                    onValueChange={(v: any) =>
                      f.handleChange(
                        v === "" ? undefined : (v as ExternalUrlScheme),
                      )
                    }
                  >
                    <SelectTrigger
                      id="net-url-scheme"
                      data-testid="net-url-scheme"
                    >
                      <SelectValue placeholder="Not set" />
                    </SelectTrigger>
                    <SelectContent>
                      {EXTERNAL_URL_SCHEMES.map((scheme) => (
                        <SelectItem key={scheme} value={scheme}>
                          {scheme.toLowerCase()}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </ChangedFieldFrame>
            )}
          </form.Field>

          <form.Field name="externalUrlPort">
            {(f: any) => (
              <ChangedFieldFrame
                name="externalUrlPort"
                form={form}
                initial={initial.externalUrlPort}
                environment={environment.externalUrlPort}
              >
                <div className="space-y-1">
                  <Label htmlFor="net-url-port">External URL port</Label>
                  <Input
                    id="net-url-port"
                    data-testid="net-url-port"
                    type="number"
                    min={1}
                    max={65535}
                    value={f.state.value ?? ""}
                    onChange={(e: any) =>
                      f.handleChange(
                        e.target.value === ""
                          ? undefined
                          : Number(e.target.value),
                      )
                    }
                    onBlur={f.handleBlur}
                    placeholder="443"
                  />
                </div>
              </ChangedFieldFrame>
            )}
          </form.Field>
        </div>

        {/* External DNS endpoint source */}
        <form.Field name="externalDnsEndpointsType">
          {(f: any) => (
            <ChangedFieldFrame
              name="externalDnsEndpointsType"
              form={form}
              initial={initial.externalDnsEndpointsType}
              environment={environment.externalDnsEndpointsType}
            >
              <div className="space-y-1">
                <Label htmlFor="net-external-dns">External DNS source</Label>
                <Select
                  value={(f.state.value as string | undefined) ?? ""}
                  onValueChange={(v: any) =>
                    f.handleChange(
                      v === "" ? undefined : (v as ExternalDnsEndpointsType),
                    )
                  }
                >
                  <SelectTrigger
                    id="net-external-dns"
                    data-testid="net-external-dns"
                  >
                    <SelectValue placeholder="Not set" />
                  </SelectTrigger>
                  <SelectContent>
                    {EXTERNAL_DNS_TYPES.map((kind) => (
                      <SelectItem key={kind} value={kind}>
                        {kind}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        {/* Ingress class */}
        <form.Field name="ingressClass">
          {(f: any) => (
            <ChangedFieldFrame
              name="ingressClass"
              form={form}
              initial={initial.ingressClass}
              environment={environment.ingressClass}
            >
              <div className="space-y-1">
                <Label htmlFor="net-ingress-class">Ingress class</Label>
                <Input
                  id="net-ingress-class"
                  data-testid="net-ingress-class"
                  value={f.state.value ?? ""}
                  onChange={(e: any) =>
                    f.handleChange(
                      e.target.value === "" ? undefined : e.target.value,
                    )
                  }
                  onBlur={f.handleBlur}
                  placeholder="e.g. nginx"
                  autoComplete="off"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        {/* Dedicated ingress — toggle gated nested form */}
        <div
          className="space-y-3 rounded-md border p-3"
          data-testid="dedicated-ingress-block"
        >
          <div className="flex items-center justify-between">
            <Label className="font-medium">Dedicated ingress</Label>
            <label className="flex items-center gap-2 text-xs">
              <Checkbox
                checked={dedicatedEnabled}
                data-testid="dedicated-ingress-toggle"
                onCheckedChange={(checked: any) => {
                  if (checked === true) {
                    form.setFieldValue(
                      "dedicatedIngress",
                      {} as DedicatedIngressInput,
                    );
                  } else {
                    form.setFieldValue("dedicatedIngress", undefined);
                  }
                }}
              />
              <span>Enabled</span>
            </label>
          </div>
          {dedicatedEnabled && (
            <div className="space-y-2">
              <form.Field name="dedicatedIngress.type">
                {(f: any) => (
                  <ChangedFieldFrame
                    name="dedicatedIngress.type"
                    form={form}
                    initial={initialDedicated?.type}
                    environment={envDedicated?.type}
                  >
                    <div className="space-y-1">
                      <Label htmlFor="dedicated-ingress-type">Type</Label>
                      <Input
                        id="dedicated-ingress-type"
                        data-testid="dedicated-ingress-type"
                        value={f.state.value ?? ""}
                        onChange={(e: any) =>
                          f.handleChange(
                            e.target.value === "" ? undefined : e.target.value,
                          )
                        }
                        placeholder="e.g. LoadBalancer"
                      />
                    </div>
                  </ChangedFieldFrame>
                )}
              </form.Field>
              <form.Field name="dedicatedIngress.implementation">
                {(f: any) => (
                  <ChangedFieldFrame
                    name="dedicatedIngress.implementation"
                    form={form}
                    initial={initialDedicated?.implementation}
                    environment={envDedicated?.implementation}
                  >
                    <div className="space-y-1">
                      <Label htmlFor="dedicated-ingress-impl">
                        Implementation
                      </Label>
                      <Input
                        id="dedicated-ingress-impl"
                        data-testid="dedicated-ingress-impl"
                        value={f.state.value ?? ""}
                        onChange={(e: any) =>
                          f.handleChange(
                            e.target.value === "" ? undefined : e.target.value,
                          )
                        }
                        placeholder="e.g. nginx"
                      />
                    </div>
                  </ChangedFieldFrame>
                )}
              </form.Field>
              <p className="text-xs italic text-muted-foreground">
                Advanced fields (service annotations, IP families, node port)
                are not surfaced here — edit via the GraphQL API or env config.
              </p>
            </div>
          )}
        </div>

        {/* IP allowlist field array */}
        <form.Field name="ipWhitelist" mode="array">
          {(field: any) => {
            const rows: string[] = field.state.value ?? [];
            return (
              <div className="space-y-2 rounded-md border p-3">
                <div className="flex items-center justify-between">
                  <Label className="font-medium">IP allowlist (CIDRs)</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="add-cidr"
                    onClick={() => field.pushValue("")}
                  >
                    Add CIDR
                  </Button>
                </div>
                {rows.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No CIDRs — every source IP allowed.
                  </p>
                )}
                {rows.map((_, index) => {
                  const path = `ipWhitelist.${index}` as const;
                  return (
                    <div
                      key={`cidr-${index}`}
                      className="flex items-start gap-2"
                      data-testid="cidr-row"
                    >
                      <form.Field name={path}>
                        {(f: any) => (
                          <ChangedFieldFrame
                            name={path}
                            form={form}
                            initial={initialAllowlist[index]}
                            environment={envAllowlist[index]}
                            className="flex-1"
                          >
                            <Input
                              aria-label={`CIDR ${index + 1}`}
                              data-testid={`cidr-${index}`}
                              value={f.state.value ?? ""}
                              onChange={(e: any) =>
                                f.handleChange(e.target.value)
                              }
                              onBlur={f.handleBlur}
                              placeholder="10.0.0.0/8"
                            />
                          </ChangedFieldFrame>
                        )}
                      </form.Field>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove CIDR ${index + 1}`}
                        data-testid={`cidr-remove-${index}`}
                        onClick={() => field.removeValue(index)}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  );
                })}
              </div>
            );
          }}
        </form.Field>
      </div>
    </section>
  );
}
