import { describe, it, expect } from "vitest";
import { classifyStaleness } from "./classifyStaleness";

const NOW = new Date("2026-05-14T12:00:00.000Z");

function at(secondsAgo: number): string {
  return new Date(NOW.getTime() - secondsAgo * 1_000).toISOString();
}

describe("classifyStaleness", () => {
  it("returns fresh just under 30s", () => {
    expect(classifyStaleness(at(29.9), NOW)).toBe("fresh");
  });

  it("returns stale at exactly 30s", () => {
    expect(classifyStaleness(at(30), NOW)).toBe("stale");
  });

  it("returns stale at 60s", () => {
    expect(classifyStaleness(at(60), NOW)).toBe("stale");
  });

  it("returns stale just under 2min", () => {
    expect(classifyStaleness(at(119.9), NOW)).toBe("stale");
  });

  it("returns not_reporting at exactly 2min", () => {
    expect(classifyStaleness(at(120), NOW)).toBe("not_reporting");
  });

  it("returns not_reporting when null", () => {
    expect(classifyStaleness(null, NOW)).toBe("not_reporting");
  });

  it("returns not_reporting when undefined", () => {
    expect(classifyStaleness(undefined, NOW)).toBe("not_reporting");
  });

  it("returns not_reporting for unparseable timestamp", () => {
    expect(classifyStaleness("not-a-date", NOW)).toBe("not_reporting");
  });

  it("returns fresh for future timestamps (clock skew)", () => {
    expect(classifyStaleness(at(-5), NOW)).toBe("fresh");
  });
});
