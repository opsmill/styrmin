import type { ReactNode } from "react";
import { ConfigSummaryCard } from "@/components/deployment/configuration/ConfigSummaryCard";
import { DEFAULT_BACKUP_TTL } from "@/lib/backup-ttl";
import {
  CLUSTER_CONFIG_LABELS as LABELS,
  DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION,
  DEFAULT_DEDICATED_INGRESS_TYPE,
  DEFAULT_EXTERNAL_URL_SCHEME,
  DEFAULT_INGRESS_CLASS,
  DEFAULT_INGRESS_SERVICE_TYPE,
  DEFAULT_RUNTIME_CLASS,
  NOT_SET,
} from "@/components/cluster/ClusterConfigFields.helpers";

type JsonObject = Record<string, unknown>;

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
        <Row
          label={LABELS.ingress_class}
          value={withDefault(config.ingress_class, DEFAULT_INGRESS_CLASS)}
        />
        <Row label={LABELS.fqdn_suffix} value={display(config.fqdn_suffix)} />
        <Row
          label={LABELS.external_url_scheme}
          value={withDefault(
            config.external_url_scheme,
            DEFAULT_EXTERNAL_URL_SCHEME,
          )}
        />
        <Row
          label={LABELS.external_url_port}
          value={
            isSet(config.external_url_port)
              ? display(config.external_url_port)
              : "Scheme default"
          }
        />
        <Row
          label={LABELS.external_dns_endpoints_type}
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
      <ConfigSummaryCard title={LABELS.dedicated_ingress}>
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
    <ConfigSummaryCard title={LABELS.dedicated_ingress}>
      <Rows>
        <Row
          label={LABELS.implementation}
          value={withDefault(
            ingress.implementation,
            DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION,
          )}
        />
        <Row
          label={LABELS.routing_type}
          value={withDefault(ingress.type, DEFAULT_DEDICATED_INGRESS_TYPE)}
        />
        <Row
          label={LABELS.service_type}
          value={withDefault(service.type, DEFAULT_INGRESS_SERVICE_TYPE)}
        />
        <Row
          label={LABELS.load_balancer_ip}
          value={display(service.load_balancer_ip)}
        />
        <Row
          label={LABELS.external_traffic_policy}
          value={display(service.external_traffic_policy)}
        />
        <Row label={LABELS.ip_families} value={display(service.ip_families)} />
        <Row
          label={LABELS.ip_family_policy}
          value={display(service.ip_family_policy)}
        />
        <Row label={LABELS.node_port} value={display(service.node_port)} />
        <Row
          label={LABELS.service_annotations}
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
          label={LABELS.standard_storage_class}
          value={standard ? display(standard.storage_class) : "Not configured"}
        />
        <Row
          label={LABELS.fast_storage_class}
          value={fast ? display(fast.storage_class) : "Not configured"}
        />
        <Row label={LABELS.db_size} value={display(config.db_size)} />
      </Rows>
    </ConfigSummaryCard>
  );
}

function RuntimeSection({ config }: { config: JsonObject }) {
  return (
    <ConfigSummaryCard title="Runtime">
      <Rows>
        <Row
          label={LABELS.runtime_class}
          value={withDefault(config.runtime_class, DEFAULT_RUNTIME_CLASS)}
        />
      </Rows>
      <p
        className="mt-3 text-xs text-muted-foreground"
        data-testid="cluster-scheduling-hint"
      >
        Scheduling is set on each environment or deployment, not on the cluster.
      </p>
    </ConfigSummaryCard>
  );
}

function BackupSection({ config }: { config: JsonObject }) {
  return (
    <ConfigSummaryCard title="Backups">
      <Rows>
        <Row
          label={LABELS.backup_ttl}
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
      <RuntimeSection config={cfg} />
      <BackupSection config={cfg} />
      <CapabilitiesSection capabilities={capabilities} />
      <OtherSettingsSection config={cfg} />
    </div>
  );
}
