import { describe, it, expect } from "vitest";
import { serviceOverridesSchema } from "./ServiceOverridesSection";

describe("serviceOverridesSchema", () => {
  it("accepts a valid override list", () => {
    const result = serviceOverridesSchema.safeParse([
      { driverServiceName: "api", overrideName: "my-api" },
      { driverServiceName: "worker", overrideName: "my-worker" },
    ]);
    expect(result.success).toBe(true);
  });

  it("rejects an override name with uppercase letters", () => {
    const result = serviceOverridesSchema.safeParse([
      { driverServiceName: "api", overrideName: "BadName" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate driver service names", () => {
    const result = serviceOverridesSchema.safeParse([
      { driverServiceName: "api", overrideName: "a" },
      { driverServiceName: "api", overrideName: "b" },
    ]);
    expect(result.success).toBe(false);
  });
});
