import { describe, it, expect } from "vitest";
import { fieldError } from "./field-error";

describe("fieldError", () => {
  it("returns a string error as is", () => {
    expect(fieldError("Name is required")).toBe("Name is required");
  });

  it("returns the message of a standard-schema issue", () => {
    expect(fieldError({ message: "Name is required", path: ["name"] })).toBe(
      "Name is required",
    );
  });

  it("falls back to a generic message for anything else", () => {
    expect(fieldError(undefined)).toBe("Invalid value");
    expect(fieldError(42)).toBe("Invalid value");
  });
});
