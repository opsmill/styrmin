import { Box } from "lucide-react";
import type { DriverVersionDetail } from "../types";
import { isPlainObject } from "../json-guards";

interface ComponentsTabProps {
  components: DriverVersionDetail["components"];
  componentConfigs: DriverVersionDetail["componentConfigs"];
}

/**
 * Components tab — structured rows per FR-009 / FR-018.
 *
 * The `components` GraphQL field is a JSON scalar (`unknown` on the TS side).
 * Per `data-model.md`, it must be a plain object (not null, not an array) to
 * render; anything else degrades to the empty state. Each value within
 * `components` must also be a plain object; entries that fail this check are
 * silently skipped.
 *
 * For each well-shaped `[componentName, componentDecl]` entry we render:
 *   - the component name (mono, matches version-number visual style),
 *   - the declared component container (from `componentConfigs`), or an
 *     explicit "None declared" state,
 *   - `identifier.label` (when a plain object) as a key/value list,
 *   - any other declared scalar properties as additional key/value rows,
 *   - any other declared shallow-dict properties expanded one level deep.
 *
 * Critically: NO `<pre>` and NO `JSON.stringify` of component data anywhere.
 */
export function ComponentsTab({
  components,
  componentConfigs,
}: ComponentsTabProps) {
  if (!isPlainObject(components) || Object.keys(components).length === 0) {
    return (
      <p
        className="text-sm italic text-muted-foreground"
        data-testid="driver-components-empty"
      >
        This version declares no components
      </p>
    );
  }

  const entries = Object.entries(components).filter(
    (entry): entry is [string, Record<string, unknown>] =>
      isPlainObject(entry[1]),
  );

  if (entries.length === 0) {
    return (
      <p
        className="text-sm italic text-muted-foreground"
        data-testid="driver-components-empty"
      >
        This version declares no components
      </p>
    );
  }

  const containers = new Map(
    componentConfigs.map((cc) => [cc.name, cc.container ?? null]),
  );

  return (
    <div
      className="grid gap-3 sm:grid-cols-2"
      data-testid="driver-components-list"
    >
      {entries.map(([name, decl]) => (
        <ComponentRow
          key={name}
          name={name}
          decl={decl}
          container={containers.get(name) ?? null}
        />
      ))}
    </div>
  );
}

interface ComponentRowProps {
  name: string;
  decl: Record<string, unknown>;
  container: string | null;
}

function ComponentRow({ name, decl, container }: ComponentRowProps) {
  const fields = flattenDecl(decl);
  return (
    <div
      className="rounded-lg border border-border bg-muted/30 p-4"
      data-testid="driver-component-row"
      data-component-name={name}
    >
      <div className="flex items-center gap-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-background">
          <Box className="h-4 w-4 text-muted-foreground" />
        </span>
        <span className="font-mono text-[13px] font-medium text-foreground">
          {name}
        </span>
      </div>
      <div
        className="mt-2 flex items-baseline gap-2 text-xs"
        data-testid="driver-component-container"
      >
        <span className="text-muted-foreground">Container</span>
        {container ? (
          <span className="truncate font-mono text-[13px]" title={container}>
            {container}
          </span>
        ) : (
          <span
            className="italic text-muted-foreground"
            title="The driver declares no container for this component, so env vars are not applied to it"
          >
            None declared
          </span>
        )}
      </div>
      {fields.length > 0 ? (
        <dl className="mt-3 grid grid-cols-[165px_1fr] gap-x-4 gap-y-1.5 border-t border-border/60 pt-3">
          {fields.map(([key, value]) => (
            <div key={key} className="contents">
              <dt
                className="truncate font-mono text-xs text-muted-foreground"
                title={key}
              >
                {key}
              </dt>
              <dd
                className="min-w-0 truncate font-mono text-[13px]"
                title={value}
              >
                {value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

/**
 * Flatten a component declaration into single-line key/value pairs for display:
 * the `identifier.label` selectors, top-level scalars, and nested objects
 * flattened one level (`backup.kind`). Arrays are joined; deeper nesting is
 * summarised; declared-but-unset (`null`) values render as an em dash rather
 * than being dropped. Keeps every card row on one line with no ragged rows.
 */
function flattenDecl(decl: Record<string, unknown>): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  const label = extractLabelDict(decl);
  if (label) {
    for (const [k, v] of Object.entries(label)) {
      if (isScalar(v)) pairs.push([k, String(v)]);
      else if (v === null) pairs.push([k, "—"]);
    }
  }
  for (const [key, value] of Object.entries(decl)) {
    // `container` has its own row, sourced from `componentConfigs`.
    if (key === "identifier" || key === "container") continue;
    if (isScalar(value)) {
      pairs.push([key, String(value)]);
    } else if (value === null) {
      pairs.push([key, "—"]);
    } else if (isPlainObject(value)) {
      for (const [k2, v2] of Object.entries(value)) {
        pairs.push([`${key}.${k2}`, summarizeValue(v2)]);
      }
    } else if (Array.isArray(value)) {
      pairs.push([key, value.filter(isScalar).map(String).join(", ") || "—"]);
    }
  }
  return pairs;
}

function summarizeValue(value: unknown): string {
  if (isScalar(value)) return String(value);
  if (Array.isArray(value)) {
    return value.filter(isScalar).map(String).join(", ") || "—";
  }
  if (isPlainObject(value)) {
    const keys = Object.keys(value);
    return keys.length === 0 ? "—" : `{ ${keys.join(", ")} }`;
  }
  return "—";
}

function isScalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function extractLabelDict(
  decl: Record<string, unknown>,
): Record<string, unknown> | null {
  const identifier = decl.identifier;
  if (!isPlainObject(identifier)) {
    return null;
  }
  const label = identifier.label;
  if (!isPlainObject(label)) {
    return null;
  }
  return label;
}
