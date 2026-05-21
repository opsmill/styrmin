import { describe, it, expect } from "vitest";
import { envVarsSchema } from "./EnvVarsSection";

describe("envVarsSchema", () => {
  it("accepts a valid list of env vars", () => {
    const result = envVarsSchema.safeParse([
      { name: "LOG_LEVEL", value: "info" },
      { name: "_DEBUG", value: "" },
    ]);
    expect(result.success).toBe(true);
  });

  it("rejects an env var name starting with a digit", () => {
    const result = envVarsSchema.safeParse([{ name: "1BAD", value: "x" }]);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate env var names", () => {
    const result = envVarsSchema.safeParse([
      { name: "FOO", value: "1" },
      { name: "FOO", value: "2" },
    ]);
    expect(result.success).toBe(false);
  });
});
