import { describe, it, expect } from "vitest";
import { parseContainerState } from "./parseContainerState";

describe("parseContainerState", () => {
  it("parses running", () => {
    expect(parseContainerState("running")).toEqual({
      state: "running",
      reason: null,
    });
  });

  it("parses unknown", () => {
    expect(parseContainerState("unknown")).toEqual({
      state: "unknown",
      reason: null,
    });
  });

  it("parses waiting:<reason>", () => {
    expect(parseContainerState("waiting:CrashLoopBackOff")).toEqual({
      state: "waiting",
      reason: "CrashLoopBackOff",
    });
  });

  it("parses terminated:<reason>", () => {
    expect(parseContainerState("terminated:OOMKilled")).toEqual({
      state: "terminated",
      reason: "OOMKilled",
    });
  });

  it("returns unknown for malformed input", () => {
    expect(parseContainerState("garbage")).toEqual({
      state: "unknown",
      reason: null,
    });
    expect(parseContainerState("")).toEqual({
      state: "unknown",
      reason: null,
    });
    expect(parseContainerState(null)).toEqual({
      state: "unknown",
      reason: null,
    });
    expect(parseContainerState(42)).toEqual({
      state: "unknown",
      reason: null,
    });
  });

  it("treats waiting with no reason as null reason", () => {
    expect(parseContainerState("waiting:")).toEqual({
      state: "waiting",
      reason: null,
    });
  });

  it("rejects unknown:<reason> as unknown with no reason", () => {
    expect(parseContainerState("frobnicating:foo")).toEqual({
      state: "unknown",
      reason: null,
    });
  });
});
