import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string;
  /**
   * Per-row marker: `true` when the deployment.config layer carried this
   * exact field (i.e. the operator explicitly wrote it on the deployment).
   * Inherited rows render identically minus the small dot — the dot is
   * the only signal of operator intent.
   */
  fromDeployment: boolean;
  /** When `true`, the value renders in the mono font (technical value). */
  mono?: boolean;
}

/**
 * Single `<dt>/<dd>` row used by the read summary cards. Centralises the
 * per-row deployment-defined marker so every section feels uniform.
 *
 * The marker is a small blue dot (`h-1.5 w-1.5 rounded-full bg-blue-500`)
 * at the row's left edge. Inherited rows leave the marker slot empty —
 * values render the same regardless of origin.
 */
export function SummaryRow({ label, value, fromDeployment, mono }: Props) {
  return (
    <div className="flex items-baseline gap-2" data-testid="summary-row">
      <span
        aria-hidden="true"
        data-from-deployment={fromDeployment ? "true" : "false"}
        className={cn(
          "mb-[2px] h-1.5 w-1.5 shrink-0 self-center rounded-full",
          fromDeployment ? "bg-blue-500" : "bg-transparent",
        )}
      />
      <dt className="flex-1 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className={cn("text-right", mono ? "font-mono text-xs" : "text-sm")}>
        {value}
      </dd>
    </div>
  );
}
