import type { ReplicaSource } from "@/generated/graphql";

/** Kubernetes `spec.replicas` is an int32; the backend rejects anything above. */
export const MAX_REPLICAS = 2147483647;

export const REPLICAS_BELOW_ONE_MESSAGE =
  "Must be 1 or more. To run no pods, stop the component.";

/** Inline error for a replica override; empty (`null`/`undefined`) means no override. */
export function replicaFieldError(value: unknown): string | undefined {
  if (value == null) return undefined;
  if (typeof value === "number" && value < 1) return REPLICAS_BELOW_ONE_MESSAGE;
  if (typeof value !== "number" || !Number.isInteger(value)) {
    return "Must be a whole number.";
  }
  if (value > MAX_REPLICAS) return `Must be ${MAX_REPLICAS} or less.`;
  return undefined;
}

/** Read a number input: an empty field is no override. */
export function parseReplicaInput(raw: string): number | undefined {
  return raw.trim() === "" ? undefined : Number(raw);
}

/** Placeholder naming the count that applies without an override. */
export function replicaPlaceholder(
  driverDefault: number | null | undefined,
): string {
  return driverDefault != null
    ? `${driverDefault} (driver default)`
    : "set by the chart";
}

/**
 * The driver default from a `Deployment.componentReplicas` row. When the
 * stored override is the source, the row's count is the override, so the
 * driver version's declared `replicas` is used instead.
 */
export function replicaDefault(
  row: { source: ReplicaSource; count?: number | null } | undefined,
  declaredReplicas: number | null | undefined,
): number | null {
  if (row?.source === "DRIVER_DEFAULT") return row.count ?? null;
  return declaredReplicas ?? null;
}

/**
 * The integer driver parameter named `replicas_<component>` (dashes as
 * underscores), the way driver versions before 023 passed a count to the
 * chart, such as `replicas_task_worker` in infrahub 4.
 */
export function replicaParameterFor<
  P extends { name: string; kind: string; label?: string | null },
>(component: string, parameters: readonly P[]): P | undefined {
  const name = `replicas_${component.replace(/-/g, "_")}`;
  return parameters.find((p) => p.name === name && p.kind === "integer");
}
