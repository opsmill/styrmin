import { describe, it, expect } from "vitest";
import { groupPodsByComponent } from "./groupPodsByComponent";

type TestPod = { id: string; componentName: string | null };

const declared = [{ name: "api" }, { name: "worker" }];

describe("groupPodsByComponent", () => {
  it("splits pods into declared / drifting / unlabeled buckets", () => {
    const pods: TestPod[] = [
      { id: "a", componentName: "api" },
      { id: "b", componentName: "api" },
      { id: "c", componentName: "worker" },
      { id: "d", componentName: "api-v2" },
      { id: "e", componentName: null },
    ];
    const groups = groupPodsByComponent(pods, declared);
    expect(groups.declared).toEqual([
      { componentName: "api", pods: [pods[0], pods[1]] },
      { componentName: "worker", pods: [pods[2]] },
    ]);
    expect(groups.drifting).toEqual([
      { componentName: "api-v2", pods: [pods[3]] },
    ]);
    expect(groups.unlabeled).toEqual([pods[4]]);
  });

  it("preserves a declared section even when it has zero pods", () => {
    const pods: TestPod[] = [{ id: "a", componentName: "api" }];
    const groups = groupPodsByComponent(pods, declared);
    expect(groups.declared).toEqual([
      { componentName: "api", pods: [pods[0]] },
      { componentName: "worker", pods: [] },
    ]);
  });

  it("emits one drifting section per observed unknown name", () => {
    const pods: TestPod[] = [
      { id: "a", componentName: "api-v2" },
      { id: "b", componentName: "api-v2" },
      { id: "c", componentName: "legacy" },
    ];
    const groups = groupPodsByComponent(pods, declared);
    expect(groups.drifting).toEqual([
      { componentName: "api-v2", pods: [pods[0], pods[1]] },
      { componentName: "legacy", pods: [pods[2]] },
    ]);
  });

  it("preserves the declaration order of declared components", () => {
    const pods: TestPod[] = [];
    const groups = groupPodsByComponent(pods, [
      { name: "z" },
      { name: "a" },
      { name: "m" },
    ]);
    expect(groups.declared.map((g) => g.componentName)).toEqual([
      "z",
      "a",
      "m",
    ]);
  });

  it("treats missing or empty componentName as unlabeled", () => {
    const pods: TestPod[] = [
      { id: "a", componentName: null },
      { id: "b", componentName: "" },
    ];
    const groups = groupPodsByComponent(pods, declared);
    expect(groups.unlabeled).toHaveLength(2);
    expect(groups.drifting).toHaveLength(0);
  });

  it("returns empty groups for empty pods + empty declared", () => {
    const groups = groupPodsByComponent([], []);
    expect(groups).toEqual({ declared: [], drifting: [], unlabeled: [] });
  });
});
