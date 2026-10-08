import { describe, it, expect } from "vitest";

import { deriveEnvHealth } from "./environment-health";

describe("deriveEnvHealth", () => {
  it("reports an environment with no deployments as pending", () => {
    expect(deriveEnvHealth([])).toBe("pending");
  });

  it("reports failed when any deployment failed", () => {
    expect(deriveEnvHealth([{ status: "running" }, { status: "failed" }])).toBe(
      "failed",
    );
  });

  it("reports pending when a deployment is still in progress", () => {
    expect(
      deriveEnvHealth([{ status: "running" }, { status: "in_progress" }]),
    ).toBe("pending");
  });

  it("reports active when every deployment is settled and none failed", () => {
    expect(
      deriveEnvHealth([{ status: "running" }, { status: "running" }]),
    ).toBe("active");
  });
});
