import { describe, expect, it } from "vitest";

import { formArrayEmptyEqual } from "./conflictMerge";

describe("formArrayEmptyEqual", () => {
  it("treats undefined/null/[]/{} as equivalent (form-array-empty tolerance)", () => {
    expect(formArrayEmptyEqual(undefined, null)).toBe(true);
    expect(formArrayEmptyEqual([], undefined)).toBe(true);
    expect(formArrayEmptyEqual({}, undefined)).toBe(true);
    expect(formArrayEmptyEqual([], {})).toBe(true);
  });

  it("distinguishes empty from non-empty", () => {
    expect(formArrayEmptyEqual([{ name: "X", value: "1" }], undefined)).toBe(
      false,
    );
    expect(formArrayEmptyEqual({ cpu: "100m" }, undefined)).toBe(false);
  });

  it("compares non-empty values structurally via JSON serialisation", () => {
    expect(formArrayEmptyEqual({ cpu: "100m" }, { cpu: "100m" })).toBe(true);
    expect(formArrayEmptyEqual({ cpu: "100m" }, { cpu: "200m" })).toBe(false);
  });
});
