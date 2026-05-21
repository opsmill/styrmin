import type { UpdateDeploymentInput } from "@/generated/graphql";
import type { DriverParameterSchema } from "@/lib/configuration-types";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
}

/**
 * Driver parameter chips for the Configuration tab.
 *
 * Renders one chip per parameter declared by `driverSchema`. Each chip shows
 * the parameter name followed by its effective value — the deployment value
 * when set, otherwise the driver default. Overridden chips render with the
 * blue "overridden" treatment; inherited (i.e. default) chips render muted.
 *
 * Driver parameters are not inherited from the environment — they live only
 * on the deployment row — so the "inherited" baseline here is the driver's
 * own default value.
 */
export function DriverParametersSummary({ current, driverSchema }: Props) {
  const params = current.parameters ?? [];
  const valueByName = new Map(params.map((p) => [p.name, p.value]));
  const schema = driverSchema ?? [];

  return (
    <ConfigSummaryCard title="Driver Parameters">
      {schema.length === 0 ? (
        <p className="text-sm text-muted-foreground italic">
          no parameters declared
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {schema.map((param) => {
            const hasOverride = valueByName.has(param.name);
            const effective = hasOverride
              ? valueByName.get(param.name)
              : param.default;
            const isOverridden =
              hasOverride && !sameJson(effective, param.default);
            return (
              <span
                key={param.name}
                data-testid="driver-parameter-chip"
                data-overridden={isOverridden ? "true" : "false"}
                className={
                  isOverridden
                    ? "inline-flex items-baseline gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-2 py-1 font-mono text-xs text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300"
                    : "inline-flex items-baseline gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1 font-mono text-xs text-muted-foreground italic"
                }
              >
                <span className="font-medium not-italic">{param.name}</span>
                <span>{formatValue(effective)}</span>
              </span>
            );
          })}
        </div>
      )}
    </ConfigSummaryCard>
  );
}

function formatValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}
