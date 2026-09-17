import { describe, it, expect } from "vitest";

import {
  exampleVersionForRange,
  invalidApplicationVersionMessage,
  isApplicationVersionShape,
} from "@/lib/applicationVersion";

describe("isApplicationVersionShape", () => {
  it.each([
    "1",
    "1.0",
    "1.0.0",
    "0.2.0",
    "2.0rc1",
    "1.0.post1",
    "1.0.0-beta+build.1",
    // Forms the backend parser also accepts (PEP 440 v-prefix and epoch).
    "v1.6.0",
    "V1.6.0",
    "1!1.6.0",
  ])("accepts %s", (value) => {
    expect(isApplicationVersionShape(value)).toBe(true);
  });

  it.each(["tata", "", "v", "vv1.0.0", "!1.0", "1.", ".1", "1..0", "latest"])(
    "rejects %j",
    (value) => {
      expect(isApplicationVersionShape(value)).toBe(false);
    },
  );
});

describe("exampleVersionForRange", () => {
  it("borrows the inclusive lower bound padded to three components", () => {
    expect(exampleVersionForRange(">=1.5,<2.0")).toBe("1.5.0");
    expect(exampleVersionForRange(">=2.15,<2.17")).toBe("2.15.0");
    expect(exampleVersionForRange("==1.0.0")).toBe("1.0.0");
    expect(exampleVersionForRange("~=1.4.2")).toBe("1.4.2");
  });

  it("drops the example when a != clause rules the lower bound out", () => {
    expect(exampleVersionForRange(">=1.5,<2.0,!=1.5.0")).toBeNull();
    expect(exampleVersionForRange(">=1.5,<2.0,!=1.5")).toBeNull();
    expect(exampleVersionForRange(">=1.5,<2.0,!=1.5.*")).toBeNull();
    expect(exampleVersionForRange(">=1.5.0,<2.0,!=1.5")).toBeNull();
  });

  it("keeps the example when the exclusion targets another version", () => {
    expect(exampleVersionForRange(">=1.5,<2.0,!=1.6.0")).toBe("1.5.0");
    expect(exampleVersionForRange(">=1.5,<2.0,!=1.50")).toBe("1.5.0");
    expect(exampleVersionForRange(">=1.5,<2.0,!=1.5.1")).toBe("1.5.0");
  });

  it("skips exclusive or upper-only clauses", () => {
    expect(exampleVersionForRange("<2.0")).toBeNull();
    expect(exampleVersionForRange(">1.0,<2.0")).toBeNull();
    expect(exampleVersionForRange("<2.0, >=1.5")).toBe("1.5.0");
  });
});

describe("invalidApplicationVersionMessage", () => {
  it("quotes the selected driver's range with an example", () => {
    expect(invalidApplicationVersionMessage(">=1.5,<2.0")).toBe(
      "Enter a version in the supported range >=1.5,<2.0, for example 1.5.0",
    );
  });

  it("omits the example when the range has no inclusive lower bound", () => {
    expect(invalidApplicationVersionMessage("<2.0")).toBe(
      "Enter a version in the supported range <2.0",
    );
  });

  it("falls back to generic wording without a usable range", () => {
    const generic = "Enter a valid application version such as 1.0.0";
    expect(invalidApplicationVersionMessage(undefined)).toBe(generic);
    expect(invalidApplicationVersionMessage(null)).toBe(generic);
    expect(invalidApplicationVersionMessage("")).toBe(generic);
    expect(invalidApplicationVersionMessage("*")).toBe(generic);
  });
});
