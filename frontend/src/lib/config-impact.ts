import type {
  ConfigurationDiff,
  DiffKind,
  ImpactEntry,
  ImpactRule,
  ImpactSeverity,
  ImpactSummary,
} from "./configuration-types";

/**
 * Evaluate a `ConfigurationDiff` against a list of `ImpactRule`s and
 * return a deduplicated `ImpactSummary`. See
 * `specs/011-unified-deployment-config/contracts/impact-rule-table.md`.
 *
 * Contract:
 *  1. Iterate `diff.entries`; for each entry, find every rule whose
 *     matcher matches.
 *  2. Group firings by `consequence` text to deduplicate.
 *  3. Order entries by descending severity, then by first-appearance.
 *  4. `topSeverity` is the max across entries (or `"informational"` when
 *     no rule fires).
 *  5. Empty diff → `{entries: [], topSeverity: "informational"}` — never crash.
 */
export function evaluateImpact(
  diff: ConfigurationDiff,
  rules: ImpactRule[],
): ImpactSummary {
  // Track each consequence in insertion order, with a Map for O(1) lookup.
  const byConsequence = new Map<
    string,
    { severity: ImpactSeverity; triggeringPaths: string[]; order: number }
  >();
  let nextOrder = 0;

  for (const entry of diff.entries) {
    for (const rule of rules) {
      if (!matchPath(rule.matcher, entry.path, entry.kind, entry.after)) {
        continue;
      }
      const existing = byConsequence.get(rule.consequence);
      if (existing) {
        // Bump severity to the higher of the two (rule may fire twice
        // across DiffEntries with mismatched severities, though in
        // practice the rule's severity is fixed).
        if (severityRank(rule.severity) > severityRank(existing.severity)) {
          existing.severity = rule.severity;
        }
        if (!existing.triggeringPaths.includes(entry.path)) {
          existing.triggeringPaths.push(entry.path);
        }
      } else {
        byConsequence.set(rule.consequence, {
          severity: rule.severity,
          triggeringPaths: [entry.path],
          order: nextOrder,
        });
        nextOrder += 1;
      }
    }
  }

  const entries: ImpactEntry[] = [...byConsequence.entries()]
    .map(([consequence, value]) => ({
      consequence,
      severity: value.severity,
      triggeringPaths: value.triggeringPaths,
      order: value.order,
    }))
    .sort((a, b) => {
      const sevDelta = severityRank(b.severity) - severityRank(a.severity);
      if (sevDelta !== 0) return sevDelta;
      return a.order - b.order;
    })
    .map(({ consequence, severity, triggeringPaths }) => ({
      consequence,
      severity,
      triggeringPaths,
    }));

  const topSeverity: ImpactSeverity =
    entries.length === 0
      ? "informational"
      : entries.reduce<ImpactSeverity>(
          (acc, entry) =>
            severityRank(entry.severity) > severityRank(acc)
              ? entry.severity
              : acc,
          "informational",
        );

  return { entries, topSeverity };
}

function severityRank(severity: ImpactSeverity): number {
  switch (severity) {
    case "informational":
      return 0;
    case "warning":
      return 1;
    case "high":
      return 2;
  }
}

// ---------------------------------------------------------------------------
// Glob matcher
// ---------------------------------------------------------------------------

/**
 * Match a glob-style `pattern` against the dotted `path` of a `DiffEntry`,
 * with optional `value:` and `kind:` qualifiers.
 *
 * Glob syntax (applied to the path):
 *  - `.` segment separator (the path is split on `.` and on `[`)
 *  - `*` matches a single path segment
 *  - `**` matches zero or more segments
 *  - `[*]` matches any array key segment
 *
 * Path segmentation: a path like `scheduling.tolerations[gpu].effect`
 * decomposes into segments `["scheduling", "tolerations", "[gpu]",
 * "effect"]`. Pattern segments are written the same way:
 * `scheduling.tolerations[*].effect` → `["scheduling", "tolerations",
 * "[*]", "effect"]`.
 *
 * Qualifier suffix:
 *  - `value:X` — only matches when `after === "X"` (case-sensitive).
 *  - `kind:add|remove|change` — only matches when `kind === ...`.
 */
export function matchPath(
  pattern: string,
  path: string,
  kind: DiffKind,
  after: string,
): boolean {
  // Split off any qualifier suffix.
  const parts = pattern.split(" ");
  const matcher = parts[0];
  const qualifiers = parts.slice(1);

  for (const qualifier of qualifiers) {
    const colonIdx = qualifier.indexOf(":");
    if (colonIdx === -1) continue;
    const k = qualifier.slice(0, colonIdx);
    const v = qualifier.slice(colonIdx + 1);
    if (k === "value") {
      if (after !== v) return false;
    } else if (k === "kind") {
      if (kind !== (v as DiffKind)) return false;
    }
  }

  const patternSegments = segmentize(matcher);
  const pathSegments = segmentize(path);
  return matchSegments(patternSegments, 0, pathSegments, 0);
}

/**
 * Decompose a dotted/bracketed path into segments. `[x]` and `.` both act
 * as segment boundaries; `[x]` segments retain their brackets so a
 * matcher segment `[*]` can match them without colliding with a bare
 * `*` matching a plain segment.
 */
function segmentize(input: string): string[] {
  if (input === "") return [];
  const segments: string[] = [];
  let buffer = "";
  let i = 0;
  while (i < input.length) {
    const ch = input[i];
    if (ch === ".") {
      if (buffer.length > 0) {
        segments.push(buffer);
        buffer = "";
      }
      i += 1;
      continue;
    }
    if (ch === "[") {
      if (buffer.length > 0) {
        segments.push(buffer);
        buffer = "";
      }
      const closeIdx = input.indexOf("]", i);
      if (closeIdx === -1) {
        // Unbalanced bracket — treat the remainder as a single segment.
        segments.push(input.slice(i));
        return segments;
      }
      segments.push(input.slice(i, closeIdx + 1));
      i = closeIdx + 1;
      continue;
    }
    buffer += ch;
    i += 1;
  }
  if (buffer.length > 0) segments.push(buffer);
  return segments;
}

function matchSegments(
  pattern: string[],
  pi: number,
  path: string[],
  si: number,
): boolean {
  while (pi < pattern.length) {
    const p = pattern[pi];
    if (p === "**") {
      // Try every possible remaining suffix of `path`. `**` matches zero
      // or more segments.
      if (pi === pattern.length - 1) return true;
      for (let k = si; k <= path.length; k += 1) {
        if (matchSegments(pattern, pi + 1, path, k)) return true;
      }
      return false;
    }
    if (si >= path.length) return false;
    const s = path[si];
    if (p === "*") {
      // Bare `*` matches any plain (non-bracket) segment.
      if (s.startsWith("[")) return false;
    } else if (p === "[*]") {
      // `[*]` matches any bracket segment.
      if (!s.startsWith("[")) return false;
    } else if (p !== s) {
      return false;
    }
    pi += 1;
    si += 1;
  }
  return si === path.length;
}
