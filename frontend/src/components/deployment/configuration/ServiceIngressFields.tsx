import { useId } from "react";

import type { ServiceConfigInput } from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fqdnSuffixError } from "@/lib/fqdn-suffix";
import { ingressClassError } from "@/lib/ingress-class";
import { getsIngress } from "@/lib/service-ingress";

/** A service of the deployment or of the selected driver version. */
export interface IngressServiceRef {
  driverServiceName: string;
  /** Only an `external` service of kind `http` or `https` gets an Ingress; others get no field. */
  scope: string;
  kind: string;
}

interface Props {
  services: readonly IngressServiceRef[];
  /** The override rows of the form (`services` of the deployment config input). */
  value: readonly ServiceConfigInput[] | null | undefined;
  onChange: (rows: ServiceConfigInput[]) => void;
}

type IngressField = "ingressClass" | "fqdnSuffix";

function withField(
  rows: readonly ServiceConfigInput[],
  name: string,
  field: IngressField,
  text: string,
): ServiceConfigInput[] {
  const next = [...rows];
  const index = next.findIndex((row) => row?.name === name);
  if (index === -1) {
    next.push({ name, [field]: text });
  } else {
    next[index] = { ...next[index], [field]: text };
  }
  return next;
}

/**
 * Ingress class and FQDN suffix of each external `http` or `https` service (#598, FR-015).
 *
 * An override applies to one service only; an empty field means the value
 * resolved from the deployment, environment or cluster applies. A service that
 * is not external, or is external with kind `tcp` or `udp`, has no field,
 * because Styrmin builds no Ingress for it (FR-009). Shared by the Services section of the edit drawer and the deploy
 * form, so both offer the same fields with the same labels and validation.
 *
 * The ingress class ({@link ingressClassError}) and the FQDN suffix
 * ({@link fqdnSuffixError}) are checked as the backend checks them; an invalid
 * value sets `aria-invalid` on its input and names the rule in the message the
 * input is described by.
 */
export function ServiceIngressFields({ services, value, onChange }: Props) {
  const idPrefix = useId();
  const external = services.filter(getsIngress);
  if (external.length === 0) return null;
  const rows = value ?? [];

  return (
    <div className="space-y-3">
      <p
        data-testid="service-ingress-override-note"
        className="text-xs text-muted-foreground"
      >
        An overridden Ingress carries only the ingress class. The IP allow-list,
        the external DNS record and the application address are not applied to
        it.
      </p>
      {external.map(({ driverServiceName: name }) => {
        const row = rows.find((candidate) => candidate?.name === name);
        const ingressClass = row?.ingressClass ?? "";
        const fqdnSuffix = row?.fqdnSuffix ?? "";
        const classError = ingressClassError(ingressClass);
        const suffixError = fqdnSuffixError(fqdnSuffix);
        const base = `${idPrefix}-${name}`;
        const classErrorId = `${base}-class-error`;
        const errorId = `${base}-suffix-error`;
        return (
          <div
            key={name}
            data-testid="service-ingress-row"
            className="space-y-2 rounded-md border p-3"
          >
            <p className="font-mono text-xs font-semibold">{name}</p>
            <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <div className="space-y-1">
                <Label htmlFor={`${base}-class`} className="text-xs">
                  Ingress class
                </Label>
                <Input
                  id={`${base}-class`}
                  aria-label={`Ingress class for ${name}`}
                  aria-invalid={classError ? true : undefined}
                  aria-describedby={classError ? classErrorId : undefined}
                  value={ingressClass}
                  onChange={(e) =>
                    onChange(
                      withField(rows, name, "ingressClass", e.target.value),
                    )
                  }
                  placeholder="inherited"
                  autoComplete="off"
                />
                {classError ? (
                  <p id={classErrorId} className="text-xs text-destructive">
                    {classError}
                  </p>
                ) : null}
              </div>
              <div className="space-y-1">
                <Label htmlFor={`${base}-suffix`} className="text-xs">
                  FQDN suffix
                </Label>
                <Input
                  id={`${base}-suffix`}
                  aria-label={`FQDN suffix for ${name}`}
                  aria-invalid={suffixError ? true : undefined}
                  aria-describedby={suffixError ? errorId : undefined}
                  value={fqdnSuffix}
                  onChange={(e) =>
                    onChange(
                      withField(rows, name, "fqdnSuffix", e.target.value),
                    )
                  }
                  placeholder="inherited"
                  autoComplete="off"
                />
                {suffixError ? (
                  <p id={errorId} className="text-xs text-destructive">
                    {suffixError}
                  </p>
                ) : null}
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Clear ingress override for ${name}`}
                disabled={!ingressClass && !fqdnSuffix}
                onClick={() =>
                  onChange(rows.filter((candidate) => candidate?.name !== name))
                }
                className="mt-5"
              >
                Clear
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
