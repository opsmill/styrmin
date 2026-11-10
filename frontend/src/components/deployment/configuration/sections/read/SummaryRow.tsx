import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string;
  /**
   * Per-row marker: `true` when the deployment.config layer carried this
   * exact field (i.e. the operator explicitly wrote it on the deployment).
   * Inherited rows render identically minus the marker — the marker is
   * the only signal of operator intent.
   */
  fromDeployment: boolean;
  /** When `true`, the value renders in the mono font (technical value). */
  mono?: boolean;
  /**
   * Optional text mark next to the value: `Overridden` when the value is set
   * on this deployment for this row, `Inherited` when it is resolved from a
   * wider scope. Used by the per-service rows (#598, FR-016), where the colour
   * dot alone is not enough to say which of the two applies.
   */
  mark?: "Overridden" | "Inherited";
}

/**
 * Single `<dt>/<dd>` row used by the read summary cards. Centralises the
 * per-row deployment-defined marker so every section feels uniform.
 *
 * The marker is a small filled blue disc with a contrasting ring at the
 * row's left edge. The dual fill+ring signal works for colour-blind users
 * (the ring is a non-colour shape change), and a visually-hidden text
 * label exposes the same information to screen readers (FR-028).
 * Inherited rows leave the marker slot empty.
 */
export function SummaryRow({
  label,
  value,
  fromDeployment,
  mono,
  mark,
}: Props) {
  return (
    <div className="flex items-baseline gap-2" data-testid="summary-row">
      <span
        role="img"
        aria-label={
          fromDeployment ? "Set on this deployment" : "Inherited value"
        }
        data-from-deployment={fromDeployment ? "true" : "false"}
        className={cn(
          "mb-[2px] h-2 w-2 shrink-0 self-center rounded-full",
          fromDeployment
            ? "bg-blue-500 ring-1 ring-blue-700 dark:ring-blue-300"
            : "bg-transparent",
        )}
      />
      <dt className="flex-1 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      {mark ? (
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {mark}
        </span>
      ) : null}
      <dd className={cn("text-right", mono ? "font-mono text-xs" : "text-sm")}>
        {value}
      </dd>
    </div>
  );
}
