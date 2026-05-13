import { describe, it, expect } from "vitest";
import { roleLabel } from "@/auth/roleLabel";

describe("roleLabel", () => {
  it("maps ADMIN to 'Admin'", () => {
    expect(roleLabel("ADMIN")).toBe("Admin");
  });

  it("maps READ_WRITE to 'Read/write'", () => {
    expect(roleLabel("READ_WRITE")).toBe("Read/write");
  });

  it("maps READ_ONLY to 'Read-only'", () => {
    expect(roleLabel("READ_ONLY")).toBe("Read-only");
  });

  it("falls back to a stable placeholder for unknown / nullish values", () => {
    // Cast through unknown so we can exercise the defensive branch without
    // relaxing the public type contract. An unrecognised enum value passes
    // through verbatim so screenshots make the drift obvious; null /
    // undefined collapse to "Unknown" because rendering the literal string
    // "null" in the UI would be worse than a placeholder.
    expect(roleLabel("MYSTERY" as unknown as "ADMIN")).toBe("MYSTERY");
    expect(roleLabel(null)).toBe("Unknown");
    expect(roleLabel(undefined)).toBe("Unknown");
  });
});
