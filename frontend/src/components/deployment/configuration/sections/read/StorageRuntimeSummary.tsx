import type { UpdateDeploymentInput } from "@/generated/graphql";
import { cn } from "@/lib/utils";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
}

/**
 * Read-only summary for `dbSize`, `standardStorage.storageClass`, and
 * `nodeSelector`. Rendered as a horizontal strip of three label/value
 * pairs in small-caps mono labels (per Paper mock D2).
 */
export function StorageRuntimeSummary({ current, environment }: Props) {
  const dbSize = resolve(current.dbSize, environment.dbSize, (v) => v ?? "—");
  const storageClass = resolve(
    current.standardStorage?.storageClass,
    environment.standardStorage?.storageClass,
    (v) => v ?? "—",
  );
  const nodeSelector = resolve(
    current.nodeSelector,
    environment.nodeSelector,
    (v) => v ?? "—",
  );

  return (
    <ConfigSummaryCard title="Storage & Runtime">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Pair label="DB SIZE" {...dbSize} />
        <Pair label="STORAGE CLASS" {...storageClass} />
        <Pair label="NODE SELECTOR" {...nodeSelector} />
      </div>
    </ConfigSummaryCard>
  );
}

function Pair({
  label,
  value,
  inherited,
}: {
  label: string;
  value: string;
  inherited: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span
        data-inherited={inherited ? "true" : "false"}
        className={cn(
          "font-mono text-sm",
          inherited
            ? "italic text-muted-foreground"
            : "font-medium text-blue-700 dark:text-blue-300",
        )}
      >
        {value}
        {inherited ? <span className="ml-1 not-italic">(env)</span> : null}
      </span>
    </div>
  );
}

function resolve<T>(
  deploymentValue: T | null | undefined,
  environmentValue: T | null | undefined,
  formatter: (v: T | null | undefined) => string,
): { value: string; inherited: boolean } {
  if (deploymentValue !== undefined && deploymentValue !== null) {
    return { value: formatter(deploymentValue), inherited: false };
  }
  if (environmentValue !== undefined && environmentValue !== null) {
    return { value: formatter(environmentValue), inherited: true };
  }
  return { value: "not set", inherited: true };
}
