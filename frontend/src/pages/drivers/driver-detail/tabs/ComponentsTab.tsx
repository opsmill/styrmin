import type { DriverVersionDetail } from "../types";
import { isPlainObject } from "../json-guards";

interface ComponentsTabProps {
  components: DriverVersionDetail["components"];
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
 *   - `identifier.label` (when a plain object) as a key/value list,
 *   - any other declared scalar properties as additional key/value rows,
 *   - any other declared shallow-dict properties expanded one level deep.
 *
 * Critically: NO `<pre>` and NO `JSON.stringify` of component data anywhere.
 */
export function ComponentsTab({ components }: ComponentsTabProps) {
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

  return (
    <div className="flex flex-col gap-3" data-testid="driver-components-list">
      {entries.map(([name, decl]) => (
        <ComponentRow key={name} name={name} decl={decl} />
      ))}
    </div>
  );
}

interface ComponentRowProps {
  name: string;
  decl: Record<string, unknown>;
}

function ComponentRow({ name, decl }: ComponentRowProps) {
  const labelDict = extractLabelDict(decl);
  const otherEntries = Object.entries(decl).filter(
    ([key]) => key !== "identifier",
  );

  return (
    <div
      className="rounded-lg border border-border bg-card p-4"
      data-testid="driver-component-row"
      data-component-name={name}
    >
      <h3 className="font-mono text-sm font-semibold text-foreground">
        {name}
      </h3>
      {labelDict && Object.keys(labelDict).length > 0 ? (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            identifier.label
          </p>
          <KeyValueList entries={Object.entries(labelDict)} />
        </div>
      ) : null}
      {otherEntries.length > 0 ? (
        <div className="mt-3 flex flex-col gap-2">
          {otherEntries.map(([key, value]) => (
            <ComponentField key={key} fieldKey={key} value={value} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ComponentField({
  fieldKey,
  value,
}: {
  fieldKey: string;
  value: unknown;
}) {
  if (isScalar(value)) {
    return (
      <div className="grid grid-cols-[minmax(0,160px)_1fr] gap-2 text-sm">
        <span className="truncate font-mono text-xs text-muted-foreground">
          {fieldKey}
        </span>
        <span className="break-words">{String(value)}</span>
      </div>
    );
  }
  if (isPlainObject(value)) {
    return (
      <div>
        <p className="font-mono text-xs text-muted-foreground">{fieldKey}</p>
        <KeyValueList entries={Object.entries(value)} />
      </div>
    );
  }
  if (Array.isArray(value)) {
    return (
      <div className="grid grid-cols-[minmax(0,160px)_1fr] gap-2 text-sm">
        <span className="truncate font-mono text-xs text-muted-foreground">
          {fieldKey}
        </span>
        <span className="text-muted-foreground">[...]</span>
      </div>
    );
  }
  // null / undefined / other — render as em dash to avoid JSON fallback.
  return (
    <div className="grid grid-cols-[minmax(0,160px)_1fr] gap-2 text-sm">
      <span className="truncate font-mono text-xs text-muted-foreground">
        {fieldKey}
      </span>
      <span className="text-muted-foreground">—</span>
    </div>
  );
}

function KeyValueList({ entries }: { entries: Array<[string, unknown]> }) {
  return (
    <dl className="mt-1 grid grid-cols-[minmax(0,160px)_1fr] gap-x-2 gap-y-1 text-sm">
      {entries.map(([k, v]) => (
        <div className="contents" key={k}>
          <dt className="truncate font-mono text-xs text-muted-foreground">
            {k}
          </dt>
          <dd className="break-words">{renderValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (isScalar(value)) {
    return String(value);
  }
  if (Array.isArray(value)) {
    return "[...]";
  }
  // Plain object one-level-deeper: show a compact "{ k1, k2 }" summary
  // without JSON-stringifying values.
  if (isPlainObject(value)) {
    const keys = Object.keys(value);
    return keys.length === 0 ? "{}" : `{ ${keys.join(", ")} }`;
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
