export type PodLike = {
  componentName?: string | null;
};

export type DeclaredComponentLike = {
  name: string;
};

export type PodGroups<P> = {
  declared: Array<{ componentName: string; pods: P[] }>;
  drifting: Array<{ componentName: string; pods: P[] }>;
  unlabeled: P[];
};

/**
 * Implements ADR-007 in the UI: three buckets by observed `styrmin/component`
 * label, never collapsing drift into a generic "Ungrouped" group.
 *
 * - declared: one entry per declared component, in declaration order,
 *   including components with zero observed pods (rendered as "no pods").
 * - drifting: one entry per observed `component_name` that is not declared.
 * - unlabeled: pods whose `component_name` is null/missing.
 */
export function groupPodsByComponent<P extends PodLike>(
  pods: readonly P[],
  declaredComponents: readonly DeclaredComponentLike[],
): PodGroups<P> {
  const declaredNames = new Set(declaredComponents.map((c) => c.name));

  const declaredBuckets = new Map<string, P[]>();
  for (const c of declaredComponents) declaredBuckets.set(c.name, []);

  const driftingBuckets = new Map<string, P[]>();
  const unlabeled: P[] = [];

  for (const pod of pods) {
    const name = pod.componentName;
    if (!name) {
      unlabeled.push(pod);
    } else if (declaredNames.has(name)) {
      declaredBuckets.get(name)!.push(pod);
    } else {
      let bucket = driftingBuckets.get(name);
      if (!bucket) {
        bucket = [];
        driftingBuckets.set(name, bucket);
      }
      bucket.push(pod);
    }
  }

  return {
    declared: declaredComponents.map((c) => ({
      componentName: c.name,
      pods: declaredBuckets.get(c.name) ?? [],
    })),
    drifting: Array.from(driftingBuckets.entries()).map(
      ([componentName, pods]) => ({ componentName, pods }),
    ),
    unlabeled,
  };
}
