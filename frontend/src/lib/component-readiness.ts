export type ComponentReadinessState =
  | "ready"
  | "not_ready"
  | "failed"
  | "no_pods"
  | "disabled";

export interface ComponentReadiness {
  state: ComponentReadinessState;
  /** Explains the state, for the indicator's tooltip and accessible name. */
  label: string;
  /** Tailwind background class for the indicator dot. */
  dot: string;
}

type PodLike = {
  componentName?: string | null;
  phase: string;
  ready: boolean;
};

const DOT: Record<ComponentReadinessState, string> = {
  ready: "bg-success",
  not_ready: "bg-warning",
  failed: "bg-destructive",
  no_pods: "bg-muted-foreground/30",
  disabled: "bg-muted-foreground/30",
};

function readiness(
  state: ComponentReadinessState,
  label: string,
): ComponentReadiness {
  return { state, label, dot: DOT[state] };
}

/**
 * The state of one component of a deployment, from the deployment's status
 * and the pods the agent reported for that component.
 *
 * A component is ready only when the deployment is running and every pod of
 * the component that has not finished (phase other than SUCCEEDED or FAILED,
 * such as an evicted pod) is ready. A component with no such pod shows
 * `no_pods`, never `ready`: a component stopped to zero replicas, or one whose
 * pods carry no `styrmin/component` label, which Styrmin sets only on the pods
 * of a Deployment or a StatefulSet.
 */
export function deriveComponentReadiness({
  componentName,
  enabled,
  deploymentStatus,
  pods,
}: {
  componentName: string;
  enabled: boolean;
  deploymentStatus: string;
  pods: readonly PodLike[];
}): ComponentReadiness {
  if (!enabled) return readiness("disabled", "Disabled");

  const status = deploymentStatus.toLowerCase();
  if (status === "failed") return readiness("failed", "Deployment failed");
  if (status === "deleted")
    return readiness("no_pods", "Deployment is deleted");
  if (status !== "running")
    return readiness("not_ready", `Deployment is ${status}`);

  const active = pods.filter(
    (pod) =>
      pod.componentName === componentName &&
      pod.phase !== "SUCCEEDED" &&
      pod.phase !== "FAILED",
  );
  if (active.length === 0)
    return readiness("no_pods", "No pod reported for this component");

  const ready = active.filter((pod) => pod.ready).length;
  const label = `${ready} of ${active.length} pods ready`;
  return readiness(ready === active.length ? "ready" : "not_ready", label);
}
