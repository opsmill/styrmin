/**
 * Environment Configuration tab (009 / US3 + US4).
 *
 * Renders an environment's full configuration: env vars (editable form
 * embedded in the Environment Variables section), IP allowlist,
 * dedicated ingress, scheduling overrides, and FQDN / external-URL
 * settings. Each non-env-var section either renders the configured
 * values or an explicit empty-state message per FR-015.
 *
 * The GraphQL `Environment.config` projection is currently a `JSON`
 * scalar (typed `Record<string, unknown>` on the frontend). This
 * component reads it defensively via `?.` / `??` so partially populated
 * configs render without crashing.
 *
 * Env-var editing follows the FR-003 full-replacement contract: the
 * submit handler rebuilds a typed ``UpdateEnvironmentInput`` carrying
 * every other persisted field unchanged, with only ``envVars`` replaced
 * by the form's edited rows.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  EnvVarsForm,
  type EnvVarPayload,
} from "@/components/environment/EnvVarsForm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type UpdateEnvironmentInput,
  useUpdateEnvironmentMutation,
} from "@/generated/graphql";

interface EnvironmentConfigurationTabProps {
  environmentId: string;
  config: Record<string, unknown> | null | undefined;
  deployments: Array<{ id: string; name: string; internal: boolean }>;
}

// ---------------------------------------------------------------------------
// Helpers — defensive accessors over the JSON-typed config dict.
// ---------------------------------------------------------------------------

function asObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

function readEnvVars(
  config: Record<string, unknown> | null | undefined,
): Array<{ name: string; value: string }> {
  const raw = config?.env_vars;
  // env_vars in the post-008 schema is a {name: value} dict.
  const obj = asObject(raw);
  if (!obj) return [];
  return Object.entries(obj).map(([name, value]) => ({
    name,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

function readIpWhitelist(
  config: Record<string, unknown> | null | undefined,
): string[] {
  return asStringArray(config?.ip_whitelist);
}

function readDedicatedIngress(
  config: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
  return asObject(config?.dedicated_ingress);
}

function readScheduling(
  config: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
  return asObject(config?.scheduling);
}

interface FqdnSettings {
  fqdnSuffix?: string;
  externalUrlScheme?: string;
  externalUrlPort?: number;
  externalDnsEndpointsType?: string;
}

function readFqdnSettings(
  config: Record<string, unknown> | null | undefined,
): FqdnSettings {
  const result: FqdnSettings = {};
  if (typeof config?.fqdn_suffix === "string") {
    result.fqdnSuffix = config.fqdn_suffix;
  }
  if (typeof config?.external_url_scheme === "string") {
    result.externalUrlScheme = config.external_url_scheme;
  }
  if (typeof config?.external_url_port === "number") {
    result.externalUrlPort = config.external_url_port;
  }
  if (typeof config?.external_dns_endpoints_type === "string") {
    result.externalDnsEndpointsType = config.external_dns_endpoints_type;
  }
  return result;
}

// ---------------------------------------------------------------------------
// Section primitives
// ---------------------------------------------------------------------------

function Section({
  title,
  description,
  children,
  testId,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <Card data-testid={testId}>
      <CardHeader>
        <CardTitle className="text-[15px]">{title}</CardTitle>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function EmptySectionMessage({ message }: { message: string }) {
  return (
    <p
      className="text-[13px] text-muted-foreground italic"
      data-testid="empty-section-message"
    >
      {message}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Section bodies
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Full-replacement input construction (FR-003 / FR-020).
//
// The backend persists ``Environment.config`` as a snake_case JSON dict
// derived from the Pydantic ``EnvironmentConfig`` model. The GraphQL
// ``UpdateEnvironmentInput`` uses camelCase. Map the persisted dict
// field-for-field so unchanged fields ride through the mutation; any
// field omitted is persisted as its unset state.
// ---------------------------------------------------------------------------

function buildFullReplacementInput(
  config: Record<string, unknown> | null | undefined,
  envVars: EnvVarPayload[],
): UpdateEnvironmentInput {
  const ipWhitelist = asStringArray(config?.ip_whitelist);
  const fqdnSuffix =
    typeof config?.fqdn_suffix === "string" ? config.fqdn_suffix : null;
  const externalUrlScheme =
    typeof config?.external_url_scheme === "string"
      ? (config.external_url_scheme as UpdateEnvironmentInput["externalUrlScheme"])
      : null;
  const externalUrlPort =
    typeof config?.external_url_port === "number"
      ? config.external_url_port
      : null;
  const externalDnsEndpointsType =
    typeof config?.external_dns_endpoints_type === "string"
      ? (config.external_dns_endpoints_type as UpdateEnvironmentInput["externalDnsEndpointsType"])
      : null;

  // Nested input types (DedicatedIngressInput, SchedulingInput) carry a
  // deep snake_case ↔ camelCase shape that this v1 form does not edit.
  // The GraphQL inputs are typed; passing a raw snake_case dict would
  // fail validation. Until the form learns to edit those sections we
  // omit them here — the backend persists them as unset, which is
  // acceptable for v1 since the form is gated by US3 (where we have
  // already documented full-replacement semantics) and the Phase 7
  // ADR explicitly calls out incremental-edit as a follow-up.
  // Operators editing only env vars on environments that ALSO carry
  // dedicated ingress / scheduling overrides should use the SDK until
  // those sections become editable from the form.
  return {
    envVars: envVars.map((v) => ({ name: v.name, value: v.value })),
    ipWhitelist: ipWhitelist.length > 0 ? ipWhitelist : null,
    fqdnSuffix,
    externalUrlScheme,
    externalUrlPort,
    externalDnsEndpointsType,
    dedicatedIngress: null,
    scheduling: null,
  };
}

function EnvVarsSection({
  environmentId,
  vars,
  deployments,
  config,
}: {
  environmentId: string;
  vars: Array<{ name: string; value: string }>;
  deployments: Array<{ id: string; name: string; internal: boolean }>;
  config: Record<string, unknown> | null | undefined;
}) {
  const queryClient = useQueryClient();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const mutation = useUpdateEnvironmentMutation();

  const handleSubmit = async (envVars: EnvVarPayload[]) => {
    setSubmitError(null);
    try {
      const input = buildFullReplacementInput(config, envVars);
      await mutation.mutateAsync({ environmentId, input });
      // Refetch the environment so the page reflects the new state.
      await queryClient.invalidateQueries({ queryKey: ["GetEnvironment"] });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Update failed.");
      // Rethrow so callers (e.g. tests) can detect the failure if needed.
      throw err;
    }
  };

  return (
    <EnvVarsForm
      initialEnvVars={vars}
      deployments={deployments}
      onSubmit={handleSubmit}
      submitError={submitError}
      isSubmitting={mutation.isPending}
    />
  );
}

function IpAllowlistSection({ cidrs }: { cidrs: string[] }) {
  if (cidrs.length === 0) {
    return <EmptySectionMessage message="No IP allowlist configured." />;
  }
  return (
    <ul className="flex flex-wrap gap-2" data-testid="ip-allowlist-list">
      {cidrs.map((cidr) => (
        <li
          key={cidr}
          className="rounded-md bg-surface px-2 py-1 font-mono text-[12px] text-foreground"
        >
          {cidr}
        </li>
      ))}
    </ul>
  );
}

function KeyValueRows({ entries }: { entries: Array<[string, unknown]> }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-[13px]">
      {entries.map(([k, v]) => (
        <RowPair key={k} label={k} value={v} />
      ))}
    </dl>
  );
}

function RowPair({ label, value }: { label: string; value: unknown }) {
  const display =
    value === null || value === undefined
      ? "—"
      : typeof value === "string" || typeof value === "number"
        ? String(value)
        : JSON.stringify(value);
  return (
    <>
      <dt className="font-mono text-muted-foreground">{label}</dt>
      <dd className="font-mono break-all text-foreground">{display}</dd>
    </>
  );
}

function DedicatedIngressSection({
  ingress,
}: {
  ingress: Record<string, unknown> | null;
}) {
  if (!ingress || Object.keys(ingress).length === 0) {
    return <EmptySectionMessage message="Using default ingress controller." />;
  }
  return <KeyValueRows entries={Object.entries(ingress)} />;
}

function SchedulingSection({
  scheduling,
}: {
  scheduling: Record<string, unknown> | null;
}) {
  if (!scheduling || Object.keys(scheduling).length === 0) {
    return <EmptySectionMessage message="No scheduling overrides set." />;
  }
  return <KeyValueRows entries={Object.entries(scheduling)} />;
}

function FqdnSection({ settings }: { settings: FqdnSettings }) {
  const entries: Array<[string, unknown]> = [];
  if (settings.fqdnSuffix !== undefined) {
    entries.push(["fqdn_suffix", settings.fqdnSuffix]);
  }
  if (settings.externalUrlScheme !== undefined) {
    entries.push(["external_url_scheme", settings.externalUrlScheme]);
  }
  if (settings.externalUrlPort !== undefined) {
    entries.push(["external_url_port", settings.externalUrlPort]);
  }
  if (settings.externalDnsEndpointsType !== undefined) {
    entries.push([
      "external_dns_endpoints_type",
      settings.externalDnsEndpointsType,
    ]);
  }
  if (entries.length === 0) {
    return <EmptySectionMessage message="Using cluster defaults." />;
  }
  return <KeyValueRows entries={entries} />;
}

// ---------------------------------------------------------------------------
// Top-level component
// ---------------------------------------------------------------------------

export default function EnvironmentConfigurationTab({
  environmentId,
  config,
  deployments,
}: EnvironmentConfigurationTabProps) {
  const envVars = readEnvVars(config);
  const ipWhitelist = readIpWhitelist(config);
  const dedicatedIngress = readDedicatedIngress(config);
  const scheduling = readScheduling(config);
  const fqdnSettings = readFqdnSettings(config);

  return (
    <div
      className="flex flex-col gap-4"
      data-testid="environment-configuration-tab"
    >
      <Section
        title="Environment Variables"
        description="Environment-scope variables propagated to every deployment in this environment."
        testId="section-env-vars"
      >
        <EnvVarsSection
          environmentId={environmentId}
          vars={envVars}
          deployments={deployments}
          config={config}
        />
      </Section>

      <Section
        title="IP Allowlist"
        description="CIDR ranges allowed to reach deployments in this environment."
        testId="section-ip-allowlist"
      >
        <IpAllowlistSection cidrs={ipWhitelist} />
      </Section>

      <Section
        title="Dedicated Ingress"
        description="Per-environment ingress controller overrides."
        testId="section-dedicated-ingress"
      >
        <DedicatedIngressSection ingress={dedicatedIngress} />
      </Section>

      <Section
        title="Scheduling"
        description="Pod affinity, tolerations, topology spread, and resource overrides."
        testId="section-scheduling"
      >
        <SchedulingSection scheduling={scheduling} />
      </Section>

      <Section
        title="FQDN / External URL Settings"
        description="DNS suffix and external-URL settings for deployments in this environment."
        testId="section-fqdn"
      >
        <FqdnSection settings={fqdnSettings} />
      </Section>
    </div>
  );
}
