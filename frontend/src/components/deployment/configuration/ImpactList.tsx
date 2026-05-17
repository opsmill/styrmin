import { AlertTriangle, Info, AlertOctagon } from "lucide-react";
import type {
  ImpactEntry,
  ImpactSeverity,
  ImpactSummary,
} from "@/lib/configuration-types";
import { cn } from "@/lib/utils";

interface Props {
  summary: ImpactSummary;
}

/**
 * Vertical list of consequence entries from an `ImpactSummary`,
 * rendered inside the Review & apply dialog (FR-021).
 *
 * When `summary.topSeverity === "high"`, a "disruptive change" amber
 * banner is shown above the list to flip the dialog into its disruptive
 * treatment per spec FR-021.
 *
 * Returns `null` when the summary is empty so the caller can mount it
 * unconditionally without leaving an empty section behind.
 */
export function ImpactList({ summary }: Props) {
  if (summary.entries.length === 0) {
    return null;
  }

  const isDisruptive = summary.topSeverity === "high";

  return (
    <div data-testid="impact-list" className="flex flex-col gap-3">
      {isDisruptive && (
        <div
          role="alert"
          data-testid="impact-disruptive-banner"
          className="flex items-start gap-2 rounded-md border border-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/60 dark:bg-amber-950/30 dark:text-amber-200"
        >
          <AlertOctagon
            className="mt-0.5 h-4 w-4 shrink-0"
            aria-hidden="true"
          />
          <div className="min-w-0">
            <p className="font-semibold">Disruptive change</p>
            <p className="text-xs text-amber-800 dark:text-amber-200/80">
              At least one consequence below may evict running pods. Review
              carefully before applying.
            </p>
          </div>
        </div>
      )}

      <ul className="flex flex-col gap-1.5">
        {summary.entries.map((entry, index) => (
          <ImpactRow key={`${entry.consequence}-${index}`} entry={entry} />
        ))}
      </ul>
    </div>
  );
}

function ImpactRow({ entry }: { entry: ImpactEntry }) {
  return (
    <li
      data-testid="impact-row"
      data-severity={entry.severity}
      className={cn(
        "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
        severityTone(entry.severity),
      )}
    >
      <SeverityIcon severity={entry.severity} />
      <span className="min-w-0 flex-1">{entry.consequence}</span>
    </li>
  );
}

function SeverityIcon({ severity }: { severity: ImpactSeverity }) {
  const className = "mt-0.5 h-4 w-4 shrink-0";
  switch (severity) {
    case "high":
      return (
        <AlertOctagon
          className={cn(className, "text-amber-700 dark:text-amber-300")}
          aria-hidden="true"
        />
      );
    case "warning":
      return (
        <AlertTriangle
          className={cn(className, "text-amber-600 dark:text-amber-300")}
          aria-hidden="true"
        />
      );
    case "informational":
      return (
        <Info
          className={cn(className, "text-sky-600 dark:text-sky-300")}
          aria-hidden="true"
        />
      );
  }
}

function severityTone(severity: ImpactSeverity): string {
  switch (severity) {
    case "high":
      return "border-amber-400 bg-amber-50 text-amber-900 dark:border-amber-500/60 dark:bg-amber-950/30 dark:text-amber-100";
    case "warning":
      return "border-amber-200 bg-amber-50/60 text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/20 dark:text-amber-100";
    case "informational":
      return "border-sky-200 bg-sky-50/60 text-sky-900 dark:border-sky-700/40 dark:bg-sky-950/20 dark:text-sky-100";
  }
}
