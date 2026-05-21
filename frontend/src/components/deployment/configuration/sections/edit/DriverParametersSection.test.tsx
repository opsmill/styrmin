import { describe, it, expect } from "vitest";
import { driverParametersSchema } from "./DriverParametersSection";
import type { ParameterDefinition } from "@/generated/graphql";

const schema: ParameterDefinition[] = [
  {
    __typename: "ParameterDefinition",
    name: "size",
    label: "Size",
    kind: "select",
    default: "small" as unknown as Record<string, unknown>,
    values: ["small", "medium", "large"],
  },
  {
    __typename: "ParameterDefinition",
    name: "debug",
    label: "Debug",
    kind: "boolean",
    default: false as unknown as Record<string, unknown>,
  },
  {
    __typename: "ParameterDefinition",
    name: "replicas",
    label: "Replicas",
    kind: "integer",
    default: 1 as unknown as Record<string, unknown>,
  },
];

describe("driverParametersSchema", () => {
  it("accepts a valid parameter list", () => {
    const result = driverParametersSchema(schema).safeParse([
      { name: "size", value: "medium" },
      { name: "debug", value: true },
      { name: "replicas", value: 3 },
    ]);
    expect(result.success).toBe(true);
  });

  it("rejects a select value outside the declared options", () => {
    const result = driverParametersSchema(schema).safeParse([
      { name: "size", value: "humongous" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects a parameter not declared by the driver", () => {
    const result = driverParametersSchema(schema).safeParse([
      { name: "mystery", value: "x" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects an integer parameter given a non-numeric value", () => {
    const result = driverParametersSchema(schema).safeParse([
      { name: "replicas", value: "three" },
    ]);
    expect(result.success).toBe(false);
  });
});
