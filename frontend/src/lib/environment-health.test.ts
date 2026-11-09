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

  it.each(["pending", "deploying", "restoring", "deleting"])(
    "reports pending while a deployment is %s",
    (status) => {
      expect(deriveEnvHealth([{ status: "running" }, { status }])).toBe(
        "pending",
      );
    },
  );

  it("reports active when every deployment is running", () => {
    expect(
      deriveEnvHealth([{ status: "running" }, { status: "running" }]),
    ).toBe("active");
  });

  it("leaves deleted deployments out", () => {
    expect(
      deriveEnvHealth([{ status: "running" }, { status: "deleted" }]),
    ).toBe("active");
    expect(deriveEnvHealth([{ status: "deleted" }])).toBe("pending");
  });
});
