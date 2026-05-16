export type KubectlCommandKind = "logs" | "describe" | "events" | "exec";

export function buildKubectlCommand(
  kind: KubectlCommandKind,
  namespace: string,
  podName: string,
): string {
  switch (kind) {
    case "logs":
      return `kubectl logs --namespace ${namespace} ${podName} --all-containers`;
    case "describe":
      return `kubectl describe pod --namespace ${namespace} ${podName}`;
    case "events":
      return `kubectl get events --namespace ${namespace} --field-selector involvedObject.name=${podName}`;
    case "exec":
      return `kubectl exec -it --namespace ${namespace} ${podName} -- /bin/sh`;
  }
}
