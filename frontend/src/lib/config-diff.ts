import type {
  ComponentConfigInput,
  EnvVarInput,
  ParameterValueInput,
  SchedulingInput,
  ServiceNameOverride,
  TolerationInput,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import type {
  ConfigurationDiff,
  DiffEntry,
  DriverParameterSchema,
  SectionId,
} from "./configuration-types";
import { SECTION_ORDER } from "./configuration-types";

/**
 * Compute the field-level differences between two `UpdateDeploymentInput`
 * snapshots, attributing each entry to one of the eight `SectionId`s.
 *
 * Array fields whose entries have a stable identity (env vars keyed by
 * `name`, tolerations keyed by `key`+`operator`, components
 * keyed by `name`, service overrides keyed by `driverServiceName`,
 * parameters keyed by `name`) use those keys instead of positional
 * indices, so a pure reorder produces no diff entries. Fields without
 * a natural key (`ipWhitelist`) compare as set-equal: present vs absent
 * generates `add`/`remove`, never `change`.
 *
 * The `driverSchema` argument is accepted for API parity with the rest
 * of the configuration libraries (and for future driver-aware behaviour
 * like labelling parameters by `label` rather than `name`). The current
 * implementation does not require it.
 */
export function diff(
  before: UpdateDeploymentInput,
  after: UpdateDeploymentInput,
  driverSchema: DriverParameterSchema,
): ConfigurationDiff {
  const entries: DiffEntry[] = [];

  // Identity
  diffScalar(entries, "identity", "name", "Name", before.name, after.name);

  // Driver Parameters (keyed by `name`). The driverSchema is reserved
  // for future driver-aware labelling but is not needed for the diff.
  void driverSchema;
  diffParameters(entries, before.parameters ?? null, after.parameters ?? null);

  // Scheduling — walk the nested SchedulingInput shape.
  diffScheduling(
    entries,
    (before.scheduling ?? null) as SchedulingInput | null,
    (after.scheduling ?? null) as SchedulingInput | null,
  );

  // Env vars (keyed by `name`)
  diffEnvVars(
    entries,
    "envVars",
    "envVars",
    "Env var",
    before.envVars ?? null,
    after.envVars ?? null,
  );

  // Networking section
  diffSet(
    entries,
    "networking",
    "ipWhitelist",
    "IP whitelist",
    before.ipWhitelist ?? null,
    after.ipWhitelist ?? null,
  );
  diffJsonObject(
    entries,
    "networking",
    "dedicatedIngress",
    "Dedicated ingress",
    before.dedicatedIngress ?? null,
    after.dedicatedIngress ?? null,
  );
  diffScalar(
    entries,
    "networking",
    "ingressClass",
    "Ingress class",
    before.ingressClass,
    after.ingressClass,
  );
  diffScalar(
    entries,
    "networking",
    "fqdnSuffix",
    "FQDN suffix",
    before.fqdnSuffix,
    after.fqdnSuffix,
  );
  diffScalar(
    entries,
    "networking",
    "externalUrlScheme",
    "External URL scheme",
    before.externalUrlScheme,
    after.externalUrlScheme,
  );
  diffScalar(
    entries,
    "networking",
    "externalUrlPort",
    "External URL port",
    before.externalUrlPort,
    after.externalUrlPort,
  );
  diffScalar(
    entries,
    "networking",
    "externalDnsEndpointsType",
    "External DNS endpoints type",
    before.externalDnsEndpointsType,
    after.externalDnsEndpointsType,
  );

  // Storage & Runtime section
  diffScalar(
    entries,
    "storageRuntime",
    "dbSize",
    "Database size",
    before.dbSize,
    after.dbSize,
  );
  diffJsonObject(
    entries,
    "storageRuntime",
    "standardStorage",
    "Standard storage",
    before.standardStorage ?? null,
    after.standardStorage ?? null,
  );
  diffScalar(
    entries,
    "storageRuntime",
    "runtimeClass",
    "Runtime class",
    before.runtimeClass,
    after.runtimeClass,
  );
  diffScalar(
    entries,
    "storageRuntime",
    "nodeSelector",
    "Node selector",
    before.nodeSelector,
    after.nodeSelector,
  );
  // Backup retention TTL (016). Storage-adjacent: it governs how long the
  // deployment's backup data is kept, so it belongs with the other
  // data-lifecycle knobs rather than in networking or scheduling.
  diffScalar(
    entries,
    "storageRuntime",
    "backupTtl",
    "Backup retention TTL",
    before.backupTtl,
    after.backupTtl,
  );

  // Service Overrides (keyed by `driverServiceName`)
  diffServiceOverrides(
    entries,
    before.serviceNameOverrides ?? null,
    after.serviceNameOverrides ?? null,
  );

  // Component Overrides (keyed by `name`)
  diffComponents(entries, before.components ?? null, after.components ?? null);

  const sectionsChanged = SECTION_ORDER.filter((section) =>
    entries.some((entry) => entry.section === section),
  );

  return {
    entries,
    sectionsChanged,
    hasChanges: entries.length > 0,
  };
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function stringifyValue(v: unknown): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function equalDeep(a: unknown, b: unknown): boolean {
  // Treat undefined and null as equivalent here — the resolver merges
  // missing/null identically for "unset". This makes the diff robust to
  // form bindings that swap between the two representations.
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  if (typeof a !== typeof b) return false;
  if (typeof a !== "object") return a === b;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) {
      if (!equalDeep(a[i], b[i])) return false;
    }
    return true;
  }
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  const keys = new Set([...Object.keys(ao), ...Object.keys(bo)]);
  for (const k of keys) {
    if (!equalDeep(ao[k], bo[k])) return false;
  }
  return true;
}

function diffScalar(
  entries: DiffEntry[],
  section: SectionId,
  path: string,
  label: string,
  before: unknown,
  after: unknown,
): void {
  const beforeIsSet = before !== undefined && before !== null;
  const afterIsSet = after !== undefined && after !== null;
  if (!beforeIsSet && !afterIsSet) return;
  if (beforeIsSet && afterIsSet) {
    if (equalDeep(before, after)) return;
    entries.push({
      section,
      path,
      label,
      before: stringifyValue(before),
      after: stringifyValue(after),
      kind: "change",
    });
    return;
  }
  if (!beforeIsSet && afterIsSet) {
    entries.push({
      section,
      path,
      label,
      before: "",
      after: stringifyValue(after),
      kind: "add",
    });
    return;
  }
  // beforeIsSet && !afterIsSet
  entries.push({
    section,
    path,
    label,
    before: stringifyValue(before),
    after: "",
    kind: "remove",
  });
}

/** Diff a free-form nested object as a single entry — sub-paths are not surfaced. */
function diffJsonObject(
  entries: DiffEntry[],
  section: SectionId,
  path: string,
  label: string,
  before: unknown,
  after: unknown,
): void {
  if (equalDeep(before ?? null, after ?? null)) return;
  diffScalar(entries, section, path, label, before, after);
}

/** Diff an unordered set of strings (e.g. `ipWhitelist`): present vs absent only. */
function diffSet(
  entries: DiffEntry[],
  section: SectionId,
  path: string,
  label: string,
  before: readonly string[] | null,
  after: readonly string[] | null,
): void {
  const b = new Set(before ?? []);
  const a = new Set(after ?? []);
  if (b.size === 0 && a.size === 0) return;
  // Treat the list as a single value when membership differs.
  const sameMembership =
    b.size === a.size && [...b].every((value) => a.has(value));
  if (sameMembership) return;
  diffScalar(entries, section, path, label, before ?? null, after ?? null);
}

function diffParameters(
  entries: DiffEntry[],
  before: readonly ParameterValueInput[] | null,
  after: readonly ParameterValueInput[] | null,
): void {
  const beforeMap = new Map((before ?? []).map((p) => [p.name, p.value]));
  const afterMap = new Map((after ?? []).map((p) => [p.name, p.value]));
  const names = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  for (const name of names) {
    diffScalar(
      entries,
      "driverParameters",
      `parameters.${name}`,
      `Parameter "${name}"`,
      beforeMap.get(name),
      afterMap.get(name),
    );
  }
}

function diffEnvVars(
  entries: DiffEntry[],
  section: SectionId,
  pathPrefix: string,
  labelPrefix: string,
  before: readonly EnvVarInput[] | null,
  after: readonly EnvVarInput[] | null,
): void {
  const beforeMap = new Map((before ?? []).map((e) => [e.name, e.value]));
  const afterMap = new Map((after ?? []).map((e) => [e.name, e.value]));
  const names = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  for (const name of names) {
    diffScalar(
      entries,
      section,
      `${pathPrefix}[${name}]`,
      `${labelPrefix} "${name}"`,
      beforeMap.get(name),
      afterMap.get(name),
    );
  }
}

function tolerationKey(t: TolerationInput): string {
  // Tolerations are matched on `key`+`operator`. Two tolerations with
  // the same key but different operators are semantically distinct (e.g.
  // `key=gpu operator=Exists` vs `key=gpu operator=Equal value=true`),
  // but a change to `effect` or `value` for a (key, operator) pair is a
  // mutation, not a remove+add.
  return [t.key ?? "", t.operator ?? ""].join("|");
}

function tolerationStableLabel(t: TolerationInput): string {
  return t.key ?? "(unset)";
}

function diffTolerations(
  entries: DiffEntry[],
  before: readonly TolerationInput[] | null,
  after: readonly TolerationInput[] | null,
): void {
  const beforeMap = new Map(
    (before ?? []).map((t) => [tolerationKey(t), t] as const),
  );
  const afterMap = new Map(
    (after ?? []).map((t) => [tolerationKey(t), t] as const),
  );
  const keys = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  for (const k of keys) {
    const b = beforeMap.get(k);
    const a = afterMap.get(k);
    const label = tolerationStableLabel(a ?? b ?? { key: "" });
    if (b && a) {
      // Compare per-field so changes report a granular `effect` path.
      for (const field of [
        "key",
        "operator",
        "value",
        "effect",
        "tolerationSeconds",
      ] as const) {
        diffScalar(
          entries,
          "scheduling",
          `scheduling.tolerations[${label}].${field}`,
          `Toleration "${label}" ${field}`,
          b[field],
          a[field],
        );
      }
    } else if (!b && a) {
      entries.push({
        section: "scheduling",
        path: `scheduling.tolerations[${label}]`,
        label: `Toleration "${label}"`,
        before: "",
        after: stringifyValue(a),
        kind: "add",
      });
    } else if (b && !a) {
      entries.push({
        section: "scheduling",
        path: `scheduling.tolerations[${label}]`,
        label: `Toleration "${label}"`,
        before: stringifyValue(b),
        after: "",
        kind: "remove",
      });
    }
  }
}

function diffScheduling(
  entries: DiffEntry[],
  before: SchedulingInput | null,
  after: SchedulingInput | null,
): void {
  if (before == null && after == null) return;
  const b: SchedulingInput = before ?? {};
  const a: SchedulingInput = after ?? {};

  // Resources — diff request/limit fields one level deep so impact rules
  // matching `scheduling.resources.**` can fire on the individual paths.
  diffResources(entries, b.resources ?? null, a.resources ?? null);

  diffScalar(
    entries,
    "scheduling",
    "scheduling.runtimeClass",
    "Runtime class",
    b.runtimeClass,
    a.runtimeClass,
  );

  diffTolerations(entries, b.tolerations ?? null, a.tolerations ?? null);

  diffJsonObject(
    entries,
    "scheduling",
    "scheduling.nodeAffinity",
    "Node affinity",
    b.nodeAffinity ?? null,
    a.nodeAffinity ?? null,
  );
  diffJsonObject(
    entries,
    "scheduling",
    "scheduling.podAffinity",
    "Pod affinity",
    b.podAffinity ?? null,
    a.podAffinity ?? null,
  );
  diffJsonObject(
    entries,
    "scheduling",
    "scheduling.podAntiAffinity",
    "Pod anti-affinity",
    b.podAntiAffinity ?? null,
    a.podAntiAffinity ?? null,
  );
  diffJsonObject(
    entries,
    "scheduling",
    "scheduling.topologySpreadConstraints",
    "Topology spread constraints",
    b.topologySpreadConstraints ?? null,
    a.topologySpreadConstraints ?? null,
  );
  diffJsonObject(
    entries,
    "scheduling",
    "scheduling.inject",
    "Post-render injection",
    b.inject ?? null,
    a.inject ?? null,
  );
}

type RrInput = {
  requests?: Record<string, string | number | null | undefined> | null;
  limits?: Record<string, string | number | null | undefined> | null;
} | null;

function diffResources(
  entries: DiffEntry[],
  before: unknown,
  after: unknown,
): void {
  const b = (before ?? {}) as NonNullable<RrInput>;
  const a = (after ?? {}) as NonNullable<RrInput>;
  for (const slot of ["requests", "limits"] as const) {
    const br = (b?.[slot] ?? {}) as Record<string, unknown>;
    const ar = (a?.[slot] ?? {}) as Record<string, unknown>;
    const keys = new Set([...Object.keys(br), ...Object.keys(ar)]);
    for (const key of keys) {
      diffScalar(
        entries,
        "scheduling",
        `scheduling.resources.${slot}.${key}`,
        `${slot === "requests" ? "Request" : "Limit"} ${key}`,
        br[key],
        ar[key],
      );
    }
  }
}

function diffServiceOverrides(
  entries: DiffEntry[],
  before: readonly ServiceNameOverride[] | null,
  after: readonly ServiceNameOverride[] | null,
): void {
  const beforeMap = new Map(
    (before ?? []).map((s) => [s.driverServiceName, s.overrideName] as const),
  );
  const afterMap = new Map(
    (after ?? []).map((s) => [s.driverServiceName, s.overrideName] as const),
  );
  const keys = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  for (const key of keys) {
    diffScalar(
      entries,
      "serviceOverrides",
      `serviceNameOverrides[${key}]`,
      `Service "${key}" override`,
      beforeMap.get(key),
      afterMap.get(key),
    );
  }
}

function diffComponents(
  entries: DiffEntry[],
  before: readonly ComponentConfigInput[] | null,
  after: readonly ComponentConfigInput[] | null,
): void {
  const beforeMap = new Map((before ?? []).map((c) => [c.name, c] as const));
  const afterMap = new Map((after ?? []).map((c) => [c.name, c] as const));
  const names = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  for (const name of names) {
    const b = beforeMap.get(name);
    const a = afterMap.get(name);
    if (b && a) {
      // Compare per-field env-var lists; each diff entry remains attributed
      // to the `componentOverrides` section per data-model.md.
      diffEnvVars(
        entries,
        "componentOverrides",
        `components[${name}].envVars`,
        `Component "${name}" env var`,
        b.envVars ?? null,
        a.envVars ?? null,
      );
    } else if (!b && a) {
      entries.push({
        section: "componentOverrides",
        path: `components[${name}]`,
        label: `Component "${name}" overrides`,
        before: "",
        after: stringifyValue(a),
        kind: "add",
      });
    } else if (b && !a) {
      entries.push({
        section: "componentOverrides",
        path: `components[${name}]`,
        label: `Component "${name}" overrides`,
        before: stringifyValue(b),
        after: "",
        kind: "remove",
      });
    }
  }
}
