import { Badge } from "@/components/ui/badge";

const FIELD_LABELS: Record<string, string> = {
  ingress_class: "Ingress Class",
  db_size: "DB Size",
  fqdn_suffix: "FQDN Suffix",
  runtime_class: "Runtime Class",
  node_selector: "Node Selector",
  ip_whitelist: "IP Whitelist",
};

const DEDICATED_INGRESS_LABELS: Record<string, string> = {
  implementation: "Implementation",
  type: "Type",
};

const STANDARD_STORAGE_LABELS: Record<string, string> = {
  storage_class: "Storage Class",
};

function ConfigField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-sm text-muted-foreground shrink-0">{label}:</span>
      <span className="text-sm font-medium font-mono">{value}</span>
    </div>
  );
}

function NestedSection({
  title,
  obj,
  labels,
}: {
  title: string;
  obj: Record<string, unknown>;
  labels: Record<string, string>;
}) {
  const entries = Object.entries(labels).filter(
    ([key]) => obj[key] != null && obj[key] !== "",
  );
  if (entries.length === 0) return null;

  return (
    <div className="space-y-1">
      <span className="text-sm font-medium">{title}</span>
      <div className="ml-4 space-y-1">
        {entries.map(([key, label]) => (
          <ConfigField key={key} label={label} value={String(obj[key])} />
        ))}
      </div>
    </div>
  );
}

export function ConfigSection({ config }: { config: Record<string, unknown> }) {
  const simpleFields = Object.entries(FIELD_LABELS).filter(
    ([key]) => config[key] != null && config[key] !== "",
  );

  const ipWhitelist = config.ip_whitelist as string[] | null | undefined;
  const dedicatedIngress = config.dedicated_ingress as Record<
    string,
    unknown
  > | null;
  const standardStorage = config.standard_storage as Record<
    string,
    unknown
  > | null;

  const hasContent =
    simpleFields.filter(([key]) => key !== "ip_whitelist").length > 0 ||
    (ipWhitelist && ipWhitelist.length > 0) ||
    dedicatedIngress != null ||
    standardStorage != null;

  if (!hasContent) {
    return (
      <p className="text-sm text-muted-foreground">No configuration set</p>
    );
  }

  return (
    <div className="space-y-3">
      {simpleFields
        .filter(([key]) => key !== "ip_whitelist")
        .map(([key, label]) => (
          <ConfigField key={key} label={label} value={String(config[key])} />
        ))}

      {ipWhitelist && ipWhitelist.length > 0 && (
        <div className="space-y-1">
          <span className="text-sm text-muted-foreground">IP Whitelist:</span>
          <div className="flex flex-wrap gap-1 ml-0">
            {ipWhitelist.map((ip) => (
              <Badge key={ip} variant="secondary" className="font-mono text-xs">
                {ip}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {dedicatedIngress && (
        <NestedSection
          title="Dedicated Ingress"
          obj={dedicatedIngress}
          labels={DEDICATED_INGRESS_LABELS}
        />
      )}

      {standardStorage && (
        <NestedSection
          title="Standard Storage"
          obj={standardStorage}
          labels={STANDARD_STORAGE_LABELS}
        />
      )}
    </div>
  );
}
