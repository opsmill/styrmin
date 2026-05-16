import type { ReactNode } from "react";
import { useStore, type AnyFormApi } from "@tanstack/react-form";
import { cn } from "@/lib/utils";

interface Props {
  /** Dotted TanStack Form field name (e.g. `scheduling.resources.cpu.request`). */
  name: string;
  /** The TanStack Form instance. Typed as `AnyFormApi` so callers can pass any form shape. */
  form: AnyFormApi;
  /** Snapshot of the original value at form mount, drawn from `ConfigurationDraft.initial`. */
  initial: unknown;
  /**
   * The corresponding value from the parent environment. Used to decide whether
   * the field's original value was inherited from the environment — when
   * `initial` equals `environment`, the "from X" annotation gets a "(env)"
   * suffix.
   */
  environment: unknown;
  children: ReactNode;
  className?: string;
}

/**
 * Wraps a single form field so it visually reflects whether the operator has
 * changed it. When the field's current value matches `initial` the children
 * render unchanged. When it differs, the frame adds an amber outline, a
 * "changed" pill, and a "from X" annotation — suffixed with "(env)" when the
 * original value came from the environment, not from an explicit deployment-
 * level setting.
 *
 * `form.useStore` (via `useStore(form.store, …)`) scopes the subscription to
 * a single field's value so the rest of the drawer does not re-render on
 * every keystroke. See `specs/011-unified-deployment-config/data-model.md`
 * — `ChangedFieldMarker`.
 */
export function ChangedFieldFrame({
  name,
  form,
  initial,
  environment,
  children,
  className,
}: Props) {
  const value = useStore(
    form.store,
    (state: { values: Record<string, unknown> }) =>
      getValueAtPath(state.values, name),
  );

  const isChanged = !valuesEqual(value, initial);
  const fromEnvironment = valuesEqual(initial, environment);

  if (!isChanged) {
    return <div className={cn("space-y-1", className)}>{children}</div>;
  }

  return (
    <div
      data-testid="changed-field-frame"
      data-changed="true"
      className={cn(
        "rounded-md border border-amber-400 bg-amber-50/40 p-2 dark:bg-amber-950/20",
        className,
      )}
    >
      <div className="mb-1 flex items-center gap-2">
        <span
          data-testid="changed-pill"
          className="inline-flex items-center rounded-md border border-amber-400 bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-900/40 dark:text-amber-200"
        >
          changed
        </span>
        <span
          data-testid="changed-from"
          className="text-xs text-muted-foreground"
        >
          from {stringifyValue(initial)}
          {fromEnvironment ? " (env)" : ""}
        </span>
      </div>
      {children}
    </div>
  );
}

/**
 * Resolve a dotted path through a values object. Handles array index segments
 * written as `foo.0.bar` — the path semantics TanStack Form uses internally
 * for nested field arrays.
 */
function getValueAtPath(values: unknown, path: string): unknown {
  if (values == null) return undefined;
  const segments = path.split(".");
  let cursor: unknown = values;
  for (const segment of segments) {
    if (cursor == null) return undefined;
    if (typeof cursor !== "object") return undefined;
    cursor = (cursor as Record<string, unknown>)[segment];
  }
  return cursor;
}

/**
 * Structural equality for the kinds of values a configuration field can hold:
 * primitives, arrays of primitives, and shallow object dictionaries. Stable
 * stringification is sufficient for the field-level dirty check — the diff
 * library does the rigorous walk when the operator opens Review & apply.
 */
function valuesEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (a == null || b == null) return false;
  if (typeof a !== typeof b) return false;
  if (typeof a === "object") {
    try {
      return JSON.stringify(a) === JSON.stringify(b);
    } catch {
      return false;
    }
  }
  return false;
}

function stringifyValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value === "" ? '""' : value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
