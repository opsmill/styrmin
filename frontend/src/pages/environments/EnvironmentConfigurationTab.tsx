/**
 * Environment Configuration tab (009 / US3).
 *
 * Read-only render of an environment's full configuration: env vars,
 * IP allowlist, dedicated ingress, scheduling overrides, and
 * FQDN / external-URL settings. Each section either renders the
 * configured values or an explicit empty-state message per FR-015.
 *
 * The GraphQL `Environment.config` projection is currently a `JSON`
 * scalar (typed `Record<string, unknown>` on the frontend). This
 * component reads it defensively via `?.` / `??` so partially populated
 * configs render without crashing. The Phase 6 (US4) edit form will
 * embed itself inside the Environment Variables section below.
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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

function EnvVarsSection({
  vars,
}: {
  vars: Array<{ name: string; value: string }>;
}) {
  if (vars.length === 0) {
    return <EmptySectionMessage message="No environment variables set." />;
  }
  return (
    <ul
      className="flex flex-col divide-y divide-border"
      data-testid="env-vars-list"
    >
      {vars.map((v) => (
        <li
          key={v.name}
          className="flex items-center gap-3 py-2 font-mono text-[13px]"
        >
          <span className="font-semibold text-foreground">{v.name}</span>
          <span className="text-muted-foreground">=</span>
          <span className="text-foreground break-all">{v.value}</span>
        </li>
      ))}
    </ul>
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
  // `environmentId` and `deployments` are passed through for the Phase 6
  // (US4) edit form which will embed in the Environment Variables section.
  // They are intentionally accepted now so the parent wiring is stable.
  void environmentId;
  void deployments;

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
        <EnvVarsSection vars={envVars} />
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
