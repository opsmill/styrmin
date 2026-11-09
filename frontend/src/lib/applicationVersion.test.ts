import { describe, it, expect } from "vitest";

import {
  exampleVersionForRange,
  invalidApplicationVersionMessage,
  isApplicationVersionShape,
  normalizeApplicationVersion,
} from "@/lib/applicationVersion";

describe("isApplicationVersionShape", () => {
  // The first group is `PEP_440_VERSIONS` in
  // backend/tests/unit/services/test_driver_version_resolution.py.
  it.each([
    "1",
    "1.0",
    "1.0.0",
    "0.2.0",
    "2.0rc1",
    "1.0.post1",
    "1.0.0-beta+build.1",
    "v1.6.0",
    "V1.6.0",
    "1!1.6.0",
    // PEP 440 also allows `_` as a separator and inside a local version.
    "1.2.3_rc1",
    "1.2.3+build_5",
    "2026.8.5",
    // Other spellings the grammar allows: normalized pre, post and dev forms.
    "1.0.0-rc.1",
    "1.0.0-alpha.1",
    "1.0.0RC1",
    "1.0-1",
    "1.0.rev2",
    "1.0.dev3",
    "1.0a1.post2.dev3+local.7",
    "0!1.0",
    "1.0.0.0",
    "1.0.0-beta",
  ])("accepts %s", (value) => {
    expect(isApplicationVersionShape(value)).toBe(true);
  });

  // Surrounding whitespace is allowed; the form trims it before it sends it.
  it.each([" 1.6.0", "1.6.0 ", " 1.6.0 ", "1.6.0\n", "\t1.6.0"])(
    "accepts padded %j",
    (value) => {
      expect(isApplicationVersionShape(value)).toBe(true);
    },
  );

  // Strings that are not PEP 440 versions, so the server refuses them:
  // image tags with a suffix, a commit hash, a date with dashes, moving tags.
  // The first six matched the pattern before it followed the PEP 440 grammar.
  it.each([
    "3f2a9c1",
    "2024-10-01",
    "1.2.3-ls45",
    "7.1.0-alpine",
    "1.2.3-SNAPSHOT",
    "1.0.0-x.7.z.92",
    "1.0.0.",
    "1.0.0-final",
    "tata",
    "",
    "   ",
    "v",
    "vv1.0.0",
    "!1.0",
    "1.",
    ".1",
    "1..0",
    "latest",
    "main",
    "2.580.1-lts-jdk21",
    "1.2.3.RELEASE",
    "1.2.3 4",
  ])("rejects %j", (value) => {
    expect(isApplicationVersionShape(value)).toBe(false);
  });
});

describe("normalizeApplicationVersion", () => {
  it("trims surrounding whitespace and keeps the rest", () => {
    expect(normalizeApplicationVersion(" 1.6.0\n")).toBe("1.6.0");
    expect(normalizeApplicationVersion("1.6.0")).toBe("1.6.0");
    expect(normalizeApplicationVersion("  ")).toBe("");
  });
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
