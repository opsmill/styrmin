import { classifyStaleness } from "./classifyStaleness";

type Variant = "declared" | "drifting" | "unlabeled";

type PodLike = {
  phase: string;
  ready: boolean;
  restartCount: number;
  lastPolledAt?: string | null;
};

/**
 * Decides whether a section should start expanded on first render.
 *
 * The intent is: collapse the happy path, expand anything the operator
 * is likely to want to investigate. Specifically the section opens if:
 *  - it's a drifting (observed-but-undeclared) component
 *  - any pod is not in a terminal-OK phase (RUNNING or SUCCEEDED)
 *  - any pod is not ready
 *  - any pod has restarted at least once
 *  - any pod's last poll is older than the stale threshold
 *
 * Empty declared sections collapse — the chip already says "no pods"
 * and there's nothing inside the section worth showing.
 */
export function shouldSectionAutoExpand(
  variant: Variant,
  pods: readonly PodLike[],
  now: Date,
): boolean {
  if (variant === "drifting") return true;
  return pods.some((pod) => {
    if (pod.phase !== "RUNNING" && pod.phase !== "SUCCEEDED") return true;
    if (!pod.ready) return true;
    if (pod.restartCount > 0) return true;
    if (classifyStaleness(pod.lastPolledAt, now) !== "fresh") return true;
    return false;
  });
}
