import type { DiffEntry } from "@/lib/configuration-types";
import { cn } from "@/lib/utils";

interface Props {
  entry: DiffEntry;
}

/**
 * One row in the Review & apply dialog's diff section.
 *
 * Renders the diff entry as a two-line patch:
 *
 *   - <path>  <before>
 *   + <path>  <after>
 *
 * Variations by `kind`:
 *  - `add`     → only the green `+` row is shown
 *  - `remove`  → only the red  `−` row is shown
 *  - `change`  → both rows are shown stacked
 *
 * Path + values render in the project's monospace font, with subtle
 * tinted backgrounds (pink/green) per row kind so a screen reader and a
 * sighted reviewer both pick up the semantic direction at a glance.
 *
 * See `frontend/src/lib/config-diff.ts` for the canonical diff producer
 * and `specs/011-unified-deployment-config/spec.md` (FR-020) for the
 * spec requirement that every diff entry MUST show `−` and `+` lines.
 */
export function DiffEntryRow({ entry }: Props) {
  const showBefore = entry.kind === "remove" || entry.kind === "change";
  const showAfter = entry.kind === "add" || entry.kind === "change";

  return (
    <div
      data-testid="diff-entry-row"
      data-path={entry.path}
      data-kind={entry.kind}
      className="flex flex-col gap-px overflow-hidden rounded-md border border-slate-200 font-mono text-xs"
    >
      {showBefore && (
        <DiffLine
          marker="-"
          path={entry.path}
          label={entry.label}
          value={entry.before}
          tone="remove"
        />
      )}
      {showAfter && (
        <DiffLine
          marker="+"
          path={entry.path}
          label={entry.label}
          value={entry.after}
          tone="add"
        />
      )}
    </div>
  );
}

interface DiffLineProps {
  marker: "-" | "+";
  path: string;
  label: string;
  value: string;
  tone: "add" | "remove";
}

function DiffLine({ marker, path, label, value, tone }: DiffLineProps) {
  const isAdd = tone === "add";
  return (
    <div
      data-testid={isAdd ? "diff-line-after" : "diff-line-before"}
      className={cn(
        "flex items-start gap-2 px-3 py-1.5",
        isAdd
          ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200"
          : "bg-rose-50 text-rose-900 dark:bg-rose-950/30 dark:text-rose-200",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "select-none font-semibold",
          isAdd ? "text-emerald-700" : "text-rose-700",
        )}
      >
        {marker}
      </span>
      <span className="min-w-0 flex-1 break-all">
        <span className="text-slate-600 dark:text-slate-300" title={path}>
          {label}
        </span>
        <span className="text-slate-400"> · </span>
        <span className="whitespace-pre-wrap">{displayValue(value)}</span>
      </span>
    </div>
  );
}

/**
 * Render an empty value as a typographic em-dash so the row still has a
 * visible payload. The diff helper already stringifies non-string values,
 * so by the time we reach this point `value` is always a string — but it
 * MAY be the empty string for `add`/`remove` cases per the
 * `ConfigurationDiff` contract.
 */
function displayValue(value: string): string {
  if (value === "") return "—";
  return value;
}
