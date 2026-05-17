import type { InheritanceState } from "@/lib/configuration-types";
import {
  computeEffectiveServices,
  type DeployedServiceRow,
  type EffectiveService,
} from "@/lib/effective-config";
import { ConfigSummaryCard } from "../../ConfigSummaryCard";

interface Props {
  /** Pass-through from `deployment.deployedServices` in the `GetDeployment` query. */
  deployedServices: readonly DeployedServiceRow[] | null | undefined;
  inheritance: InheritanceState;
}

/**
 * Read-only summary of the deployment's services — i.e. the driver-declared
 * service definitions reconciled with any deployment-level name overrides.
 *
 * Each row shows the effective (resolved) name as the primary identifier,
 * the driver-declared name when it differs (with an "overridden" pill),
 * the Kubernetes kind + port, and external URL/FQDN when surfaced by the
 * backend.
 *
 * The section identity is "Services" — overrides are a per-row attribute,
 * not the section's framing.
 */
export function ServiceOverridesSummary({
  deployedServices,
  inheritance,
}: Props) {
  const services = computeEffectiveServices(deployedServices);

  return (
    <ConfigSummaryCard title="Services" inheritance={inheritance}>
      {services.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          no services declared by the driver
        </p>
      ) : (
        <ul className="space-y-2" data-testid="services-effective-list">
          {services.map((service) => (
            <ServiceRow key={service.id} service={service} />
          ))}
        </ul>
      )}
    </ConfigSummaryCard>
  );
}

function ServiceRow({ service }: { service: EffectiveService }) {
  const externalUrl = service.humanReadableUrl ?? service.primaryUrl ?? null;
  return (
    <li
      data-testid="service-row"
      data-overridden={service.isOverridden ? "true" : "false"}
      className="flex flex-col gap-1 rounded-md border border-border bg-muted/30 px-3 py-2"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-sm font-semibold text-foreground">
          {service.resolvedName}
        </span>
        <div className="flex items-center gap-1.5">
          <span className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
            {service.kind}
          </span>
          <span className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            :{service.port}
          </span>
          {service.isOverridden ? (
            <span
              data-testid="service-overridden-pill"
              className="rounded-md border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300"
            >
              overridden
            </span>
          ) : null}
        </div>
      </div>

      {service.isOverridden ? (
        <div className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
          <span>driver default:</span>
          <span>{service.driverServiceName}</span>
        </div>
      ) : null}

      {externalUrl ? (
        <div className="font-mono text-[11px] text-muted-foreground">
          <a
            href={externalUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="hover:text-foreground hover:underline"
          >
            {externalUrl}
          </a>
        </div>
      ) : null}
    </li>
  );
}
