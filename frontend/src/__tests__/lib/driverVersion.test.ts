import { describe, it, expect } from "vitest";

import {
  formatDriverVersionLabel,
  collidingVersions,
  displayDriverVersion,
} from "@/lib/driverVersion";

describe("formatDriverVersionLabel", () => {
  it("renders the first 7 chars of contentHash for a local row", () => {
    expect(
      formatDriverVersionLabel({
        version: "1.2.3",
        contentHash: "a".repeat(64),
        sourceCommitSha: null,
      }),
    ).toBe("1.2.3@aaaaaaa");
  });

  it("renders the first 7 chars of sourceCommitSha for a git row", () => {
    expect(
      formatDriverVersionLabel({
        version: "1.2.3",
        contentHash: null,
        sourceCommitSha: "b".repeat(40),
      }),
    ).toBe("1.2.3@bbbbbbb");
  });

  it("falls back to the bare version when both fingerprints are null", () => {
    expect(
      formatDriverVersionLabel({
        version: "1.2.3",
        contentHash: null,
        sourceCommitSha: null,
      }),
    ).toBe("1.2.3");
  });

  it("prefers contentHash when both fingerprints are set (defensive)", () => {
    expect(
      formatDriverVersionLabel({
        version: "1.2.3",
        contentHash: "c".repeat(64),
        sourceCommitSha: "d".repeat(40),
      }),
    ).toBe("1.2.3@ccccccc");
  });

  it("treats empty-string fingerprints as falsy and falls back to bare version", () => {
    expect(
      formatDriverVersionLabel({
        version: "1.2.3",
        contentHash: "",
        sourceCommitSha: "",
      }),
    ).toBe("1.2.3");
  });
});

describe("collidingVersions", () => {
  it("returns only version strings that appear more than once", () => {
    const set = collidingVersions([
      { version: "1" },
      { version: "1" },
      { version: "2" },
    ]);
    expect(set.has("1")).toBe(true);
    expect(set.has("2")).toBe(false);
    expect(set.size).toBe(1);
  });

  it("is empty when every version is unique", () => {
    expect(collidingVersions([{ version: "1" }, { version: "2" }]).size).toBe(
      0,
    );
  });
});

describe("displayDriverVersion", () => {
  const v = {
    version: "1",
    contentHash: "a".repeat(64),
    sourceCommitSha: null,
  };

  it("shows the bare version when it does not collide", () => {
    expect(displayDriverVersion(v, new Set())).toBe("1");
  });

  it("appends the fingerprint only when the version collides", () => {
    expect(displayDriverVersion(v, new Set(["1"]))).toBe("1@aaaaaaa");
  });
});
