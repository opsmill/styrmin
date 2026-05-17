/**
 * Sanitisation helpers for the unified-configuration `SchedulingSection`.
 *
 * The unified drawer binds the form directly to `SchedulingInput` (camelCase,
 * screaming-snake enums), so this file only keeps the "prune empties" helper:
 * collapse empty sub-objects/arrays to `null` so the GraphQL mutation accepts
 * the partial input cleanly. The legacy `components/deployment/scheduling/`
 * directory (which carried the snake_case → camelCase translation logic) was
 * removed in feature 011, chunk 7.
 */
import type {
  AffinityBlockInput,
  AffinityTermInput,
  LabelSelectorInput,
  ResourceRequirementsInput,
  ResourceSpecInput,
  SchedulingInput,
  TolerationInput,
  TopologySpreadConstraintInput,
  WeightedAffinityTermInput,
} from "@/generated/graphql";

function nonEmptyString(v: string | null | undefined): v is string {
  return typeof v === "string" && v.trim() !== "";
}

function sanitizeLabelSelector(
  ls: LabelSelectorInput | null | undefined,
): LabelSelectorInput | undefined {
  if (!ls) return undefined;
  const out: LabelSelectorInput = {};
  const rawLabels = (ls.matchLabels ?? {}) as Record<string, string>;
  const labels: Record<string, string> = {};
  for (const [k, v] of Object.entries(rawLabels)) {
    if (k.trim() !== "") labels[k] = v;
  }
  if (Object.keys(labels).length > 0) out.matchLabels = labels;
  const exprs = (ls.matchExpressions ?? []).filter((e) => e.key.trim() !== "");
  if (exprs.length > 0) {
    out.matchExpressions = exprs.map((e) => {
      const cleaned: typeof e = { key: e.key, operator: e.operator };
      const skipValues =
        e.operator === "EXISTS" || e.operator === "DOES_NOT_EXIST";
      if (!skipValues && (e.values ?? []).length > 0) {
        cleaned.values = e.values;
      }
      return cleaned;
    });
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function sanitizeAffinityTerm(
  term: AffinityTermInput | null | undefined,
): AffinityTermInput | null {
  if (!term) return null;
  const out: AffinityTermInput = { topologyKey: term.topologyKey ?? "" };
  const ls = sanitizeLabelSelector(term.labelSelector);
  if (ls) out.labelSelector = ls;
  if (term.deploymentRef) {
    const dr = { ...term.deploymentRef };
    if (!nonEmptyString(dr.deploymentId)) delete dr.deploymentId;
    if (!nonEmptyString(dr.deploymentName)) delete dr.deploymentName;
    if (dr.deploymentId || dr.deploymentName) out.deploymentRef = dr;
  }
  // A term is valid only if it carries a target (label selector or deployment ref).
  if (!out.labelSelector && !out.deploymentRef) return null;
  return out;
}

export function sanitizeAffinityBlock(
  block: AffinityBlockInput | null | undefined,
): AffinityBlockInput | undefined {
  if (!block) return undefined;
  const out: AffinityBlockInput = {};
  const required = (block.required ?? [])
    .map(sanitizeAffinityTerm)
    .filter((t): t is AffinityTermInput => t !== null);
  const preferred = (block.preferred ?? [])
    .map((wt): WeightedAffinityTermInput | null => {
      const term = sanitizeAffinityTerm(wt.term);
      if (!term) return null;
      return { weight: wt.weight, term };
    })
    .filter((wt): wt is WeightedAffinityTermInput => wt !== null);
  if (required.length > 0) out.required = required;
  if (preferred.length > 0) out.preferred = preferred;
  if (block.replace) out.replace = true;
  return Object.keys(out).length > 0 ? out : undefined;
}

function sanitizeToleration(t: TolerationInput): TolerationInput | null {
  const out: TolerationInput = {};
  if (nonEmptyString(t.key)) out.key = t.key.trim();
  if (t.operator) out.operator = t.operator;
  if (t.operator !== "EXISTS" && nonEmptyString(t.value)) {
    out.value = t.value.trim();
  }
  if (t.effect) out.effect = t.effect;
  if (typeof t.tolerationSeconds === "number" && t.effect === "NO_EXECUTE") {
    out.tolerationSeconds = t.tolerationSeconds;
  }
  if (!out.key && !out.operator && !out.effect) return null;
  return out;
}

function sanitizeResourceSpec(
  spec: ResourceSpecInput | null | undefined,
): ResourceSpecInput | undefined {
  if (!spec) return undefined;
  const out: ResourceSpecInput = {};
  if (nonEmptyString(spec.cpu)) out.cpu = spec.cpu.trim();
  if (nonEmptyString(spec.memory)) out.memory = spec.memory.trim();
  if (nonEmptyString(spec.ephemeralStorage)) {
    out.ephemeralStorage = spec.ephemeralStorage.trim();
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

export function sanitizeResources(
  r: ResourceRequirementsInput | null | undefined,
): ResourceRequirementsInput | undefined {
  if (!r) return undefined;
  const out: ResourceRequirementsInput = {};
  const requests = sanitizeResourceSpec(r.requests);
  const limits = sanitizeResourceSpec(r.limits);
  if (requests) out.requests = requests;
  if (limits) out.limits = limits;
  return Object.keys(out).length > 0 ? out : undefined;
}

export function sanitizeTopologySpread(
  list: readonly TopologySpreadConstraintInput[] | null | undefined,
): TopologySpreadConstraintInput[] {
  return (list ?? [])
    .filter((c) => c.topologyKey.trim() !== "")
    .map((c) => {
      const out: TopologySpreadConstraintInput = {
        maxSkew: c.maxSkew,
        topologyKey: c.topologyKey.trim(),
        whenUnsatisfiable: c.whenUnsatisfiable,
      };
      const ls = sanitizeLabelSelector(c.labelSelector);
      if (ls) out.labelSelector = ls;
      if (typeof c.minDomains === "number") out.minDomains = c.minDomains;
      return out;
    });
}

/**
 * Sanitise the entire `SchedulingInput` slice of the form draft. Empty
 * sub-blocks are pruned so the diff helper compares apples-to-apples with
 * the persisted state (which also stores absent fields as `undefined`).
 *
 * Returns `undefined` when every sub-block is empty so the caller can set
 * `input.scheduling = undefined` instead of persisting an empty object.
 */
export function sanitizeScheduling(
  draft: SchedulingInput | null | undefined,
): SchedulingInput | undefined {
  if (!draft) return undefined;
  const out: SchedulingInput = {};
  const resources = sanitizeResources(draft.resources);
  if (resources) out.resources = resources;
  const tolerations = (draft.tolerations ?? [])
    .map(sanitizeToleration)
    .filter((t): t is TolerationInput => t !== null);
  if (tolerations.length > 0) out.tolerations = tolerations;
  const topology = sanitizeTopologySpread(draft.topologySpreadConstraints);
  if (topology.length > 0) out.topologySpreadConstraints = topology;
  const node = sanitizeAffinityBlock(draft.nodeAffinity);
  if (node) out.nodeAffinity = node;
  const podA = sanitizeAffinityBlock(draft.podAffinity);
  if (podA) out.podAffinity = podA;
  const podAnti = sanitizeAffinityBlock(draft.podAntiAffinity);
  if (podAnti) out.podAntiAffinity = podAnti;
  if (nonEmptyString(draft.runtimeClass)) {
    out.runtimeClass = draft.runtimeClass.trim();
  }
  if (draft.inject) {
    // Drop the inject block when every flag is undefined; keep otherwise.
    const flags = Object.values(draft.inject).filter(
      (v) => typeof v === "boolean",
    );
    if (flags.length > 0) out.inject = draft.inject;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}
