import type { ReactNode } from "react";
import { ConfigSummaryCard } from "@/components/deployment/configuration/ConfigSummaryCard";
import { DEFAULT_BACKUP_TTL } from "@/lib/backup-ttl";

type JsonObject = Record<string, unknown>;

const NOT_SET = "Not set";

// Defaults the backend applies when a key is absent (see
// ``DedicatedIngressConfig`` / ``IngressServiceConfig`` / ``BaseConfigSection``).
const DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION = "traefik";
const DEFAULT_DEDICATED_INGRESS_TYPE = "ingress";
const DEFAULT_INGRESS_SERVICE_TYPE = "LoadBalancer";
const DEFAULT_EXTERNAL_URL_SCHEME = "https";

// Keys rendered by a dedicated section; anything else lands in "Other settings".
const KNOWN_KEYS = new Set([
  "ingress_class",
  "fqdn_suffix",
  "external_url_scheme",
  "external_url_port",
  "external_dns_endpoints_type",
  "dedicated_ingress",
  "standard_storage",
  "fast_storage",
  "db_size",
  "runtime_class",
  "node_selector",
  "scheduling",
  "backup_ttl",
]);

const CAPABILITY_CATEGORY_LABELS: Record<string, string> = {
  storage: "Storage",
  ingress: "Ingress",
  backup: "Backup",
};

function asObject(value: unknown): JsonObject | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as JsonObject;
  }
  return null;
}

function isSet(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "";
}

function display(value: unknown): string {
  if (!isSet(value)) return NOT_SET;
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(display).join(", ");
  return JSON.stringify(value);
}

function withDefault(value: unknown, fallback: string): string {
  return isSet(value) ? display(value) : `${fallback} (default)`;
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2" data-testid="cluster-config-row">
      <dt className="flex-1 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="text-right font-mono text-xs break-all">{value}</dd>
    </div>
  );
}

function Rows({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-1 gap-y-2 text-sm">{children}</dl>;
}

function EmptyMessage({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function NetworkingSection({ config }: { config: JsonObject }) {
  return (
    <ConfigSummaryCard title="Networking">
      <Rows>
        <Row label="Ingress class" value={display(config.ingress_class)} />
        <Row label="FQDN suffix" value={display(config.fqdn_suffix)} />
        <Row
          label="External URL scheme"
          value={withDefault(
            config.external_url_scheme,
            DEFAULT_EXTERNAL_URL_SCHEME,
          )}
        />
        <Row
          label="External URL port"
          value={
            isSet(config.external_url_port)
              ? display(config.external_url_port)
              : "Scheme default"
          }
        />
        <Row
          label="External DNS endpoints type"
          value={display(config.external_dns_endpoints_type)}
        />
      </Rows>
    </ConfigSummaryCard>
  );
}

function DedicatedIngressSection({ config }: { config: JsonObject }) {
  const ingress = asObject(config.dedicated_ingress);
  if (!ingress) {
    return (
      <ConfigSummaryCard title="Dedicated ingress">
        <EmptyMessage>
          Not configured. Deployments use the cluster ingress class unless their
          environment configures a dedicated ingress.
        </EmptyMessage>
      </ConfigSummaryCard>
    );
  }

  const service = asObject(ingress.service) ?? {};
  const annotations = Object.entries(asObject(service.annotations) ?? {});

  return (
    <ConfigSummaryCard title="Dedicated ingress">
      <Rows>
        <Row
          label="Implementation"
          value={withDefault(
            ingress.implementation,
            DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION,
          )}
        />
        <Row
          label="Routing type"
          value={withDefault(ingress.type, DEFAULT_DEDICATED_INGRESS_TYPE)}
        />
        <Row
          label="Service type"
          value={withDefault(service.type, DEFAULT_INGRESS_SERVICE_TYPE)}
        />
        <Row
          label="Load balancer IP"
          value={display(service.load_balancer_ip)}
        />
        <Row
          label="External traffic policy"
          value={display(service.external_traffic_policy)}
        />
        <Row label="IP families" value={display(service.ip_families)} />
        <Row
          label="IP family policy"
          value={display(service.ip_family_policy)}
        />
        <Row label="NodePort" value={display(service.node_port)} />
        <Row
          label="Service annotations"
          value={
            annotations.length === 0 ? (
              NOT_SET
            ) : (
              <ul className="space-y-0.5">
                {annotations.map(([key, value]) => (
                  <li key={key}>
                    {key}: {display(value)}
                  </li>
                ))}
              </ul>
            )
          }
        />
      </Rows>
    </ConfigSummaryCard>
  );
}

function StorageSection({ config }: { config: JsonObject }) {
  const standard = asObject(config.standard_storage);
  const fast = asObject(config.fast_storage);
  return (
    <ConfigSummaryCard title="Storage">
      <Rows>
        <Row
          label="Standard storage class"
          value={standard ? display(standard.storage_class) : "Not configured"}
        />
        <Row
          label="Fast storage class"
          value={fast ? display(fast.storage_class) : "Not configured"}
        />
        <Row label="Database size" value={display(config.db_size)} />
      </Rows>
    </ConfigSummaryCard>
  );
}

function RuntimeSchedulingSection({ config }: { config: JsonObject }) {
  const scheduling = asObject(config.scheduling);
  const hasScheduling = scheduling && Object.keys(scheduling).length > 0;
  return (
    <ConfigSummaryCard title="Runtime and scheduling">
      <Rows>
        <Row label="Runtime class" value={display(config.runtime_class)} />
        <Row label="Node selector" value={display(config.node_selector)} />
      </Rows>
      <div className="mt-3">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          Scheduling defaults
        </p>
        {hasScheduling ? (
          <pre
            className="mt-1 overflow-x-auto rounded-md bg-muted/50 p-3 font-mono text-xs"
            data-testid="cluster-scheduling"
          >
            {JSON.stringify(scheduling, null, 2)}
          </pre>
        ) : (
          <EmptyMessage>Not set</EmptyMessage>
        )}
      </div>
    </ConfigSummaryCard>
  );
}

function BackupSection({ config }: { config: JsonObject }) {
  return (
    <ConfigSummaryCard title="Backups">
      <Rows>
        <Row
          label="Backup retention"
          value={withDefault(config.backup_ttl, DEFAULT_BACKUP_TTL)}
        />
      </Rows>
    </ConfigSummaryCard>
  );
}

function CapabilitiesSection({
  capabilities,
}: {
  capabilities: JsonObject | null | undefined;
}) {
  const rows: Array<{ category: string; name: string; details: string }> = [];
  for (const [category, entries] of Object.entries(capabilities ?? {})) {
    for (const [name, detail] of Object.entries(asObject(entries) ?? {})) {
      const details = Object.entries(asObject(detail) ?? {})
        .map(([key, value]) => `${key}: ${display(value)}`)
        .join(", ");
      rows.push({
        category: CAPABILITY_CATEGORY_LABELS[category] ?? category,
        name,
        details,
      });
    }
  }

  return (
    <ConfigSummaryCard title="Capabilities">
      {rows.length === 0 ? (
        <EmptyMessage>
          No capabilities. Storage and ingress capabilities appear once the
          matching settings are configured.
        </EmptyMessage>
      ) : (
        <table className="w-full text-sm" data-testid="cluster-capabilities">
          <thead>
            <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-2 pr-4 font-normal">Category</th>
              <th className="py-2 pr-4 font-normal">Name</th>
              <th className="py-2 font-normal">Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.category}/${row.name}`}
                className="border-b last:border-0"
              >
                <td className="py-2 pr-4">{row.category}</td>
                <td className="py-2 pr-4 font-mono text-xs">{row.name}</td>
                <td className="py-2 font-mono text-xs break-all">
                  {row.details}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ConfigSummaryCard>
  );
}

function OtherSettingsSection({ config }: { config: JsonObject }) {
  const extra = Object.entries(config).filter(([key]) => !KNOWN_KEYS.has(key));
  if (extra.length === 0) return null;
  return (
    <ConfigSummaryCard title="Other settings">
      <Rows>
        {extra.map(([key, value]) => (
          <Row key={key} label={key} value={display(value)} />
        ))}
      </Rows>
    </ConfigSummaryCard>
  );
}

/**
 * Read-only view of every cluster setting, grouped by area. Unset values
 * render explicitly, with the backend default when one applies.
 */
export function ClusterConfiguration({
  config,
  capabilities,
}: {
  config: JsonObject | null | undefined;
  capabilities: JsonObject | null | undefined;
}) {
  const cfg = config ?? {};
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <NetworkingSection config={cfg} />
      <DedicatedIngressSection config={cfg} />
      <StorageSection config={cfg} />
      <RuntimeSchedulingSection config={cfg} />
      <BackupSection config={cfg} />
      <CapabilitiesSection capabilities={capabilities} />
      <OtherSettingsSection config={cfg} />
    </div>
  );
}
