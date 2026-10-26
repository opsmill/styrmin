/**
 * Summarise an environment's deployments into one health value for its status
 * badge. The environment queries leave internal deployments (the ingress
 * controller) out, so they never affect the result. Deleted deployments are
 * no longer part of the environment, so they do not count either.
 *
 * The environment is healthy only when every deployment is running: a
 * deployment that is still deploying, restoring or deleting keeps it pending.
 */
export function deriveEnvHealth(deployments: { status: string }[]): string {
  const statuses = deployments
    .map((d) => d.status.toLowerCase())
    .filter((status) => status !== "deleted");
  if (statuses.length === 0) return "pending";
  if (statuses.includes("failed")) return "failed";
  if (statuses.every((status) => status === "running")) return "active";
  return "pending";
}
