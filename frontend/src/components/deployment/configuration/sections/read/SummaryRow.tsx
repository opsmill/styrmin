import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string;
  /** When `true`, the value came from the parent environment and renders muted italic. */
  inherited: boolean;
  /** When `true`, the value renders in the mono font (technical value). */
  mono?: boolean;
}

/**
 * Single `<dt>/<dd>` row used by the read summary cards. Centralises the
 * inherited-vs-overridden visual treatment so every section feels uniform.
 */
export function SummaryRow({ label, value, inherited, mono }: Props) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd
        data-inherited={inherited ? "true" : "false"}
        className={cn(
          "text-right",
          mono ? "font-mono text-xs" : "text-sm",
          inherited
            ? "italic text-muted-foreground"
            : "font-medium text-blue-700 dark:text-blue-300",
        )}
      >
        {value}
        {inherited ? <span className="ml-1 not-italic">(env)</span> : null}
      </dd>
    </div>
  );
}
