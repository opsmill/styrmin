import { describe, it, expect } from "vitest";

import { deriveComponentReadiness } from "./component-readiness";

const pod = (
  overrides: Partial<{
    componentName: string | null;
    phase: string;
    ready: boolean;
  }> = {},
) => ({ componentName: "app", phase: "RUNNING", ready: true, ...overrides });

const base = {
  componentName: "app",
  enabled: true,
  deploymentStatus: "running",
};

describe("deriveComponentReadiness", () => {
  it("reports a disabled component as disabled", () => {
    expect(
      deriveComponentReadiness({ ...base, enabled: false, pods: [pod()] })
        .state,
    ).toBe("disabled");
  });

  it("reports failed when the deployment failed, even with ready pods", () => {
    const result = deriveComponentReadiness({
      ...base,
      deploymentStatus: "failed",
      pods: [pod()],
    });
    expect(result.state).toBe("failed");
    expect(result.dot).toBe("bg-destructive");
  });

  it("reports a deleted deployment as gray, not as starting", () => {
    const result = deriveComponentReadiness({
      ...base,
      deploymentStatus: "deleted",
      pods: [],
    });
    expect(result.state).toBe("no_pods");
    expect(result.label).toBe("Deployment is deleted");
  });

  it.each(["pending", "deploying", "restoring", "deleting"])(
    "reports not ready while the deployment is %s, even with ready pods",
    (deploymentStatus) => {
      const result = deriveComponentReadiness({
        ...base,
        deploymentStatus,
        pods: [pod()],
      });
      expect(result.state).toBe("not_ready");
      expect(result.label).toBe(`Deployment is ${deploymentStatus}`);
    },
  );

  it("reports not ready when a running pod of the component is not ready", () => {
    const result = deriveComponentReadiness({
      ...base,
      pods: [pod(), pod({ ready: false })],
    });
    expect(result.state).toBe("not_ready");
    expect(result.label).toBe("1 of 2 pods ready");
    expect(result.dot).toBe("bg-warning");
  });

  it("reports not ready when a pod of the component is still pending", () => {
    expect(
      deriveComponentReadiness({
        ...base,
        pods: [pod({ phase: "PENDING", ready: false })],
      }).state,
    ).toBe("not_ready");
  });

  it("leaves finished pods out, such as an evicted pod in phase FAILED", () => {
    const result = deriveComponentReadiness({
      ...base,
      pods: [pod({ phase: "FAILED", ready: false }), pod()],
    });
    expect(result.state).toBe("ready");
    expect(result.label).toBe("1 of 1 pods ready");
  });

  it("reports no pods when the component has no pod that runs", () => {
    const result = deriveComponentReadiness({
      ...base,
      pods: [
        pod({ componentName: "other" }),
        pod({ phase: "SUCCEEDED", ready: false }),
      ],
    });
    expect(result.state).toBe("no_pods");
    expect(result.dot).not.toBe("bg-success");
  });

  it("reports ready when every running pod of the component is ready", () => {
    const result = deriveComponentReadiness({
      ...base,
      pods: [
        pod(),
        pod(),
        pod({ phase: "SUCCEEDED", ready: false }),
        pod({ componentName: "other", ready: false }),
      ],
    });
    expect(result.state).toBe("ready");
    expect(result.label).toBe("2 of 2 pods ready");
    expect(result.dot).toBe("bg-success");
  });
});
