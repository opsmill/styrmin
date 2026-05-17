import { describe, it, expect } from "vitest";
import { storageRuntimeSchema } from "./StorageRuntimeSection";

describe("storageRuntimeSchema", () => {
  it("accepts a fully populated storage/runtime block", () => {
    const result = storageRuntimeSchema.safeParse({
      dbSize: "medium",
      standardStorage: { storageClass: "standard-rwo" },
      nodeSelector: "disktype=ssd",
    });
    expect(result.success).toBe(true);
  });

  it("rejects an invalid storage class name (uppercase)", () => {
    const result = storageRuntimeSchema.safeParse({
      standardStorage: { storageClass: "Bad-Class" },
    });
    expect(result.success).toBe(false);
  });

  it("rejects an unknown dbSize value", () => {
    const result = storageRuntimeSchema.safeParse({ dbSize: "humongous" });
    expect(result.success).toBe(false);
  });
});
