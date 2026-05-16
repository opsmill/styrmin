import { describe, it, expect } from "vitest";
import { shouldSectionAutoExpand } from "./shouldSectionAutoExpand";

const NOW = new Date("2026-05-15T12:00:00.000Z");
const fresh = new Date(NOW.getTime() - 5_000).toISOString();
const stale = new Date(NOW.getTime() - 60_000).toISOString();

function pod(
  overrides: Partial<{
    phase: string;
    ready: boolean;
    restartCount: number;
    lastPolledAt: string | null;
  }> = {},
) {
  return {
    phase: "RUNNING",
    ready: true,
    restartCount: 0,
    lastPolledAt: fresh,
    ...overrides,
  };
}

describe("shouldSectionAutoExpand", () => {
  it("always expands drifting sections", () => {
    expect(shouldSectionAutoExpand("drifting", [], NOW)).toBe(true);
    expect(shouldSectionAutoExpand("drifting", [pod()], NOW)).toBe(true);
  });

  it("collapses an empty declared section", () => {
    expect(shouldSectionAutoExpand("declared", [], NOW)).toBe(false);
  });

  it("collapses an all-healthy declared section", () => {
    expect(shouldSectionAutoExpand("declared", [pod(), pod()], NOW)).toBe(
      false,
    );
  });

  it("expands when any pod is not RUNNING/SUCCEEDED", () => {
    expect(
      shouldSectionAutoExpand(
        "declared",
        [pod(), pod({ phase: "PENDING" })],
        NOW,
      ),
    ).toBe(true);
    expect(
      shouldSectionAutoExpand("declared", [pod({ phase: "FAILED" })], NOW),
    ).toBe(true);
    expect(
      shouldSectionAutoExpand("declared", [pod({ phase: "UNKNOWN" })], NOW),
    ).toBe(true);
  });

  it("treats SUCCEEDED as a healthy terminal phase", () => {
    expect(
      shouldSectionAutoExpand("declared", [pod({ phase: "SUCCEEDED" })], NOW),
    ).toBe(false);
  });

  it("expands when any pod is not ready", () => {
    expect(
      shouldSectionAutoExpand("declared", [pod({ ready: false })], NOW),
    ).toBe(true);
  });

  it("expands when any pod has restarted at least once", () => {
    expect(
      shouldSectionAutoExpand("declared", [pod({ restartCount: 1 })], NOW),
    ).toBe(true);
  });

  it("expands when any pod is stale", () => {
    expect(
      shouldSectionAutoExpand("declared", [pod({ lastPolledAt: stale })], NOW),
    ).toBe(true);
  });

  it("expands an unlabeled section the same way as declared", () => {
    expect(
      shouldSectionAutoExpand("unlabeled", [pod({ ready: false })], NOW),
    ).toBe(true);
    expect(shouldSectionAutoExpand("unlabeled", [pod()], NOW)).toBe(false);
  });
});
