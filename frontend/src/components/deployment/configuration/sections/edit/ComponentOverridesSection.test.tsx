import { describe, it, expect } from "vitest";
import { componentOverridesSchema } from "./ComponentOverridesSection";

describe("componentOverridesSchema", () => {
  it("accepts an empty list", () => {
    const result = componentOverridesSchema.safeParse([]);
    expect(result.success).toBe(true);
  });

  it("accepts a per-component env-var override", () => {
    const result = componentOverridesSchema.safeParse([
      {
        name: "server",
        envVars: [{ name: "LOG_LEVEL", value: "debug" }],
      },
    ]);
    expect(result.success).toBe(true);
  });

  it("rejects an env-var name starting with a digit", () => {
    const result = componentOverridesSchema.safeParse([
      {
        name: "server",
        envVars: [{ name: "1BAD", value: "x" }],
      },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate component-override blocks", () => {
    const result = componentOverridesSchema.safeParse([
      { name: "server", envVars: [] },
      { name: "server", envVars: [] },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate env-var names within a component block", () => {
    const result = componentOverridesSchema.safeParse([
      {
        name: "server",
        envVars: [
          { name: "LOG_LEVEL", value: "debug" },
          { name: "LOG_LEVEL", value: "info" },
        ],
      },
    ]);
    expect(result.success).toBe(false);
  });
});
