export function ConfigSummary({ config }: { config: Record<string, unknown> }) {
  const items: string[] = [];
  if (config.ingress_class) items.push(`Ingress: ${config.ingress_class}`);
  if (config.db_size) items.push(`DB: ${config.db_size}`);
  if (config.fqdn_suffix) items.push(`FQDN: ${config.fqdn_suffix}`);
  if (config.runtime_class) items.push(`Runtime: ${config.runtime_class}`);
  if (config.dedicated_ingress) items.push("Dedicated Ingress");
  if (config.standard_storage) items.push("Standard Storage");

  if (items.length === 0) return null;

  return (
    <p className="text-xs text-muted-foreground mt-1">{items.join(" · ")}</p>
  );
}
