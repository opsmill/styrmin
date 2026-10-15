import { describe, expect, it } from "vitest";

import {
  REPLICAS_BELOW_ONE_MESSAGE,
  parseReplicaInput,
  replicaDefault,
  replicaFieldError,
  replicaPlaceholder,
} from "./replicas";

describe("replicaFieldError", () => {
  it.each([undefined, null, 1, 3, 2147483647])("accepts %j", (value) => {
    expect(replicaFieldError(value)).toBeUndefined();
  });

  it.each([0, -1, -2.5])("rejects %j as below 1", (value) => {
    expect(replicaFieldError(value)).toBe(REPLICAS_BELOW_ONE_MESSAGE);
    expect(REPLICAS_BELOW_ONE_MESSAGE).toBe(
      "Must be 1 or more. To run no pods, stop the component.",
    );
  });

  it("rejects a fraction, a value above int32 and NaN", () => {
    expect(replicaFieldError(1.5)).toBe("Must be a whole number.");
    expect(replicaFieldError(Number.NaN)).toBe("Must be a whole number.");
    expect(replicaFieldError(2147483648)).toBe("Must be 2147483647 or less.");
  });
});

describe("parseReplicaInput", () => {
  it("reads an empty field as no override and a number as a number", () => {
    expect(parseReplicaInput("")).toBeUndefined();
    expect(parseReplicaInput("  ")).toBeUndefined();
    expect(parseReplicaInput("3")).toBe(3);
    expect(parseReplicaInput("0")).toBe(0);
  });
});

describe("replicaPlaceholder and replicaDefault", () => {
  it("names the driver default or the chart", () => {
    expect(replicaPlaceholder(2)).toBe("2 (driver default)");
    expect(replicaPlaceholder(null)).toBe("set by the chart");
    expect(replicaPlaceholder(undefined)).toBe("set by the chart");
  });

  it("takes the count of a DRIVER_DEFAULT row", () => {
    expect(replicaDefault({ source: "DRIVER_DEFAULT", count: 2 }, null)).toBe(
      2,
    );
  });

  it("falls back to the declared default when an override is the source", () => {
    expect(replicaDefault({ source: "OVERRIDE", count: 3 }, 2)).toBe(2);
    expect(replicaDefault({ source: "OVERRIDE", count: 3 }, null)).toBeNull();
  });

  it("returns null for the chart and for an unknown component", () => {
    expect(replicaDefault({ source: "CHART", count: null }, null)).toBeNull();
    expect(replicaDefault(undefined, undefined)).toBeNull();
  });
});
