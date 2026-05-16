import type {
  DedicatedIngressInput,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import type { InheritanceState } from "@/lib/configuration-types";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";
import { SummaryRow } from "./SummaryRow";

interface Props {
  current: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  inheritance: InheritanceState;
}

/**
 * Read-only summary for the deployment's networking-related fields:
 * `fqdnSuffix`, `externalUrl{Scheme,Port}`, `ingressClass`,
 * `externalDnsEndpointsType`, `dedicatedIngress`, and `ipWhitelist`.
 */
export function NetworkingSummary({
  current,
  environment,
  inheritance,
}: Props) {
  const suffix = resolveScalar(current.fqdnSuffix, environment.fqdnSuffix);
  const externalUrl = resolveExternalUrl(current, environment);
  const ingress = resolveScalar(current.ingressClass, environment.ingressClass);
  const externalDns = resolveScalar(
    current.externalDnsEndpointsType,
    environment.externalDnsEndpointsType,
  );
  const dedicated = resolveDedicated(
    current.dedicatedIngress,
    environment.dedicatedIngress,
  );
  const allowlist = resolveAllowlist(
    current.ipWhitelist,
    environment.ipWhitelist,
  );

  return (
    <ConfigSummaryCard title="Networking" inheritance={inheritance}>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <SummaryRow label="FQDN suffix" mono {...suffix} />
        <SummaryRow label="External URL" mono {...externalUrl} />
        <SummaryRow label="Ingress class" mono {...ingress} />
        <SummaryRow label="External DNS source" {...externalDns} />
        <SummaryRow label="Dedicated ingress" {...dedicated} />
        <SummaryRow label="IP allowlist" {...allowlist} />
      </dl>
    </ConfigSummaryCard>
  );
}

function resolveScalar(
  dep: string | null | undefined,
  env: string | null | undefined,
): { value: string; inherited: boolean } {
  if (dep != null) return { value: dep, inherited: false };
  if (env != null) return { value: env, inherited: true };
  return { value: "not set", inherited: true };
}

function resolveExternalUrl(
  current: UpdateDeploymentInput,
  environment: UpdateDeploymentInput,
): { value: string; inherited: boolean } {
  const depScheme = current.externalUrlScheme;
  const depPort = current.externalUrlPort;
  const hasDep = depScheme != null || depPort != null;
  if (hasDep) {
    return {
      value: format(
        depScheme ?? environment.externalUrlScheme,
        depPort ?? environment.externalUrlPort,
      ),
      inherited: false,
    };
  }
  if (
    environment.externalUrlScheme != null ||
    environment.externalUrlPort != null
  ) {
    return {
      value: format(environment.externalUrlScheme, environment.externalUrlPort),
      inherited: true,
    };
  }
  return { value: "not set", inherited: true };
}

function format(
  scheme: string | null | undefined,
  port: number | null | undefined,
): string {
  const s = scheme ? scheme.toLowerCase() : "—";
  const p = port ?? "—";
  return `${s}:${p}`;
}

function resolveDedicated(
  dep: DedicatedIngressInput | null | undefined,
  env: DedicatedIngressInput | null | undefined,
): { value: string; inherited: boolean } {
  const fmt = (block: DedicatedIngressInput) => {
    const parts: string[] = [];
    if (block.type) parts.push(block.type);
    if (block.implementation) parts.push(block.implementation);
    return parts.length ? parts.join(" / ") : "configured";
  };
  if (dep != null) return { value: fmt(dep), inherited: false };
  if (env != null) return { value: fmt(env), inherited: true };
  return { value: "not configured", inherited: true };
}

function resolveAllowlist(
  dep: readonly string[] | null | undefined,
  env: readonly string[] | null | undefined,
): { value: string; inherited: boolean } {
  if (dep != null) {
    return {
      value: `${dep.length} CIDR${dep.length === 1 ? "" : "s"}`,
      inherited: false,
    };
  }
  if (env != null) {
    return {
      value: `${env.length} CIDR${env.length === 1 ? "" : "s"}`,
      inherited: true,
    };
  }
  return { value: "0 CIDRs", inherited: true };
}
