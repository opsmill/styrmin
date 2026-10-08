/**
 * Summarise an environment's deployments into one health value for its status
 * badge. The environment queries leave internal deployments (the ingress
 * controller) out, so they never affect the result.
 */
export function deriveEnvHealth(deployments: { status: string }[]): string {
  if (deployments.length === 0) return "pending";
  if (deployments.some((d) => d.status === "FAILED" || d.status === "failed"))
    return "failed";
  if (
    deployments.some(
      (d) =>
        d.status === "PENDING" ||
        d.status === "pending" ||
        d.status === "in_progress",
    )
  )
    return "pending";
  return "active";
}
