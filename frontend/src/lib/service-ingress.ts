/** A service as the deployment or the driver version declares it. */
export interface IngressCandidate {
  scope: string;
  kind: string;
}

/**
 * Kinds that can sit behind an Ingress. Styrmin builds no Ingress for a `tcp` or
 * `udp` service, even when it is `external` (backend `service_gets_ingress`).
 */
const INGRESS_SERVICE_KINDS: readonly string[] = ["http", "https"];

/**
 * Whether Styrmin builds an Ingress for the service: `scope: external` and kind
 * `http` or `https`. An ingress override applies to such a service only, so the
 * drawer, the deploy form and the networking summary offer or list fields for
 * these services alone. The write is refused otherwise (`SERVICE_INGRESS_NOT_BUILT`).
 */
export function getsIngress(service: IngressCandidate): boolean {
  return (
    service.scope === "external" && INGRESS_SERVICE_KINDS.includes(service.kind)
  );
}
