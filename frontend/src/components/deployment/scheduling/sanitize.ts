import type {
  AffinityBlock,
  AffinityTerm,
  LabelSelector,
  ResourceRequirements,
  SchedulingConfig,
  Toleration,
  TopologySpreadConstraint,
  WeightedAffinityTerm,
} from "./types";

function isPlainObjectNonEmpty(
  obj: Record<string, unknown> | undefined,
): boolean {
  return !!obj && Object.keys(obj).length > 0;
}

function sanitizeLabelSelector(
  ls: LabelSelector | undefined,
): LabelSelector | undefined {
  if (!ls) return undefined;
  const result: LabelSelector = {};
  if (isPlainObjectNonEmpty(ls.match_labels)) {
    // Drop empty keys that the UI might have left from "add but didn't fill".
    const filtered = Object.fromEntries(
      Object.entries(ls.match_labels ?? {}).filter(([k]) => k.trim() !== ""),
    );
    if (Object.keys(filtered).length > 0) result.match_labels = filtered;
  }
  const exprs = (ls.match_expressions ?? []).filter((e) => e.key.trim() !== "");
  if (exprs.length > 0) {
    result.match_expressions = exprs.map((e) => {
      const out: typeof e = { key: e.key, operator: e.operator };
      if (
        e.operator !== "Exists" &&
        e.operator !== "DoesNotExist" &&
        (e.values ?? []).length > 0
      ) {
        out.values = e.values;
      }
      return out;
    });
  }
  return Object.keys(result).length > 0 ? result : undefined;
}

function sanitizeAffinityTerm(term: AffinityTerm): AffinityTerm | null {
  const out: AffinityTerm = { topology_key: term.topology_key ?? "" };
  if (term.label_selector) {
    const ls = sanitizeLabelSelector(term.label_selector);
    if (ls) out.label_selector = ls;
  }
  if (term.deployment_ref) {
    const dr = { ...term.deployment_ref };
    if (!dr.deployment_id) delete dr.deployment_id;
    if (!dr.deployment_name) delete dr.deployment_name;
    if (dr.deployment_id || dr.deployment_name) {
      out.deployment_ref = dr;
    }
  }
  // A term is valid only if it has a target (label_selector or deployment_ref).
  if (!out.label_selector && !out.deployment_ref) return null;
  return out;
}

function sanitizeAffinityBlock(
  block: AffinityBlock | undefined,
): AffinityBlock | undefined {
  if (!block) return undefined;
  const out: AffinityBlock = {};
  const required = (block.required ?? [])
    .map(sanitizeAffinityTerm)
    .filter((t): t is AffinityTerm => t !== null);
  const preferred = (block.preferred ?? [])
    .map((wt): WeightedAffinityTerm | null => {
      const term = sanitizeAffinityTerm(wt.term);
      if (!term) return null;
      return { weight: wt.weight, term };
    })
    .filter((t): t is WeightedAffinityTerm => t !== null);
  if (required.length > 0) out.required = required;
  if (preferred.length > 0) out.preferred = preferred;
  if (block.replace) out.replace = true;
  return Object.keys(out).length > 0 ? out : undefined;
}

function sanitizeToleration(t: Toleration): Toleration | null {
  const out: Toleration = {};
  if (t.key?.trim()) out.key = t.key.trim();
  if (t.operator) out.operator = t.operator;
  if (t.operator !== "Exists" && t.value?.trim()) out.value = t.value.trim();
  if (t.effect) out.effect = t.effect;
  if (typeof t.toleration_seconds === "number" && t.effect === "NoExecute") {
    out.toleration_seconds = t.toleration_seconds;
  }
  // A bare toleration with nothing but operator is meaningless.
  if (!out.key && !out.operator && !out.effect) return null;
  return out;
}

function sanitizeResources(
  r: ResourceRequirements | undefined,
): ResourceRequirements | undefined {
  if (!r) return undefined;
  const out: ResourceRequirements = {};
  for (const kind of ["requests", "limits"] as const) {
    const spec = r[kind];
    if (!spec) continue;
    const cleaned: Record<string, string> = {};
    for (const field of ["cpu", "memory", "ephemeral_storage"] as const) {
      const v = spec[field];
      if (typeof v === "string" && v.trim() !== "") cleaned[field] = v.trim();
    }
    if (Object.keys(cleaned).length > 0) out[kind] = cleaned;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function sanitizeTopologySpread(
  list: TopologySpreadConstraint[],
): TopologySpreadConstraint[] {
  return list
    .filter((c) => c.topology_key.trim() !== "")
    .map((c) => {
      const out: TopologySpreadConstraint = {
        max_skew: c.max_skew,
        topology_key: c.topology_key.trim(),
        when_unsatisfiable: c.when_unsatisfiable,
      };
      const ls = sanitizeLabelSelector(c.label_selector);
      if (ls) out.label_selector = ls;
      return out;
    });
}

export function sanitizeSchedulingConfig(
  draft: SchedulingConfig,
): SchedulingConfig {
  const out: SchedulingConfig = {};
  const tolerations = (draft.tolerations ?? [])
    .map(sanitizeToleration)
    .filter((t): t is Toleration => t !== null);
  if (tolerations.length > 0) out.tolerations = tolerations;

  const resources = sanitizeResources(draft.resources);
  if (resources) out.resources = resources;

  const topology = sanitizeTopologySpread(
    draft.topology_spread_constraints ?? [],
  );
  if (topology.length > 0) out.topology_spread_constraints = topology;

  const podAff = sanitizeAffinityBlock(draft.pod_affinity);
  if (podAff) out.pod_affinity = podAff;

  const antiAff = sanitizeAffinityBlock(draft.pod_anti_affinity);
  if (antiAff) out.pod_anti_affinity = antiAff;

  const nodeAff = sanitizeAffinityBlock(draft.node_affinity);
  if (nodeAff) out.node_affinity = nodeAff;

  if (draft.runtime_class?.trim()) {
    out.runtime_class = draft.runtime_class.trim();
  }

  return out;
}
