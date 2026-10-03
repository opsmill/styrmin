import { describe, expect, it } from "vitest";

import {
  APP_VERSION_TOKEN_RE,
  PLACEHOLDER_VERSION,
  hasAppVersionToken,
  imageReferenceMessage,
  substituteAppVersion,
  validateImageReference,
  type ImageReferenceReason,
} from "./image-reference";
import vectors from "./image-reference.vectors.json";

// Shared with backend/tests/unit/services/image_overrides/test_reference.py (research D-007).
interface Vector {
  reference: string;
  valid: boolean;
  reason?: ImageReferenceReason;
  note: string;
}

const VECTORS = vectors as Vector[];
const VALID = VECTORS.filter((v) => v.valid);
const INVALID = VECTORS.filter((v) => !v.valid);

const label = (v: Vector) => JSON.stringify(v.reference).slice(0, 48);

describe("image-reference vectors", () => {
  it("cover every grammar reason and never after_substitution", () => {
    expect(new Set(INVALID.map((v) => v.reason))).toEqual(
      new Set(["grammar", "missing_tag_or_digest", "template_expression"]),
    );
    expect(VECTORS.some((v) => v.reason === "after_substitution")).toBe(false);
  });

  it.each(VALID.map((v) => [label(v), v] as const))(
    "accepts %s",
    (_label, v) => {
      expect(validateImageReference(v.reference)).toBeNull();
    },
  );

  it.each(INVALID.map((v) => [label(v), v] as const))(
    "rejects %s",
    (_label, v) => {
      expect(validateImageReference(v.reference)).toEqual({
        reason: v.reason,
      });
    },
  );
});

describe("validateImageReference", () => {
  it("validates with the placeholder version by default", () => {
    expect(PLACEHOLDER_VERSION).toBe("0");
    expect(validateImageReference("app:{{ app.version }}")).toBeNull();
    expect(validateImageReference("app@sha256:{{ app.version }}")).toEqual({
      reason: "grammar",
    });
  });

  it("accepts a token reference with a real version", () => {
    expect(
      validateImageReference(
        "registry.example/acme/app:{{ app.version }}",
        "0.2.0",
      ),
    ).toBeNull();
  });

  it("reports after_substitution when only the real version breaks it", () => {
    expect(
      validateImageReference("app:{{ app.version }}", "1.0.0+build"),
    ).toEqual({ reason: "after_substitution" });
  });

  it("reports after_substitution when the version introduces template markers", () => {
    expect(validateImageReference("app:{{ app.version }}", "{{x}}")).toEqual({
      reason: "after_substitution",
    });
  });

  it("keeps the reference's own reason when it is invalid with any version", () => {
    expect(
      validateImageReference("App:{{ app.version }}", "1.0.0+build"),
    ).toEqual({ reason: "grammar" });
  });

  it("ignores the version for a pinned reference", () => {
    expect(validateImageReference("app:1", "1.0.0+build")).toBeNull();
    expect(validateImageReference("App:1", "1.0.0+build")).toEqual({
      reason: "grammar",
    });
  });
});

describe("substituteAppVersion", () => {
  it.each([
    ["app:{{ app.version }}", "app:1.2.3"],
    ["app:{{app.version}}", "app:1.2.3"],
    ["app:{{   app.version   }}", "app:1.2.3"],
    ["app:{{\tapp.version\n}}", "app:1.2.3"],
    [
      "r.example/{{ app.version }}/app:v{{app.version}}-x",
      "r.example/1.2.3/app:v1.2.3-x",
    ],
    ["app:1.0.0", "app:1.0.0"],
    ["app:{{ app.Version }}", "app:{{ app.Version }}"],
    ["app:{{ app.version }", "app:{{ app.version }"],
    ["app:{{ app.version }}", "app:{{ app.version }}"],
  ])("substitutes %j", (reference, expected) => {
    expect(substituteAppVersion(reference, "1.2.3")).toBe(expected);
  });

  it("inserts the version literally, never as a replacement pattern", () => {
    expect(substituteAppVersion("app:{{ app.version }}", "$&$1$$")).toBe(
      "app:$&$1$$",
    );
  });
});

describe("hasAppVersionToken / APP_VERSION_TOKEN_RE", () => {
  it.each([
    ["app:{{ app.version }}", true],
    ["app:{{app.version}}", true],
    ["app:{{   app.version   }}", true],
    ["registry.example/acme/app-{{ app.version }}:stable", true],
    ["app:1.0.0", false],
    ["app:{{ app.name }}", false],
    ["app:{{ app.Version }}", false],
    ["app:{{ app.version }", false],
    ["app:{{ app.version }}", false],
  ])("%j -> %s", (reference, expected) => {
    expect(hasAppVersionToken(reference)).toBe(expected);
    expect(APP_VERSION_TOKEN_RE.test(reference)).toBe(expected);
  });

  it("is stateless across repeated calls", () => {
    const ref = "app:{{ app.version }}";
    expect([1, 2, 3].map(() => hasAppVersionToken(ref))).toEqual([
      true,
      true,
      true,
    ]);
  });
});

describe("imageReferenceMessage", () => {
  it.each([
    ["missing_tag_or_digest", /no tag or digest/i],
    ["grammar", /not a valid image reference/i],
    ["template_expression", /only \{\{ app\.version \}\} is substituted/],
    ["after_substitution", /application version/i],
  ] as const)("describes %s", (reason, pattern) => {
    expect(imageReferenceMessage(reason)).toMatch(pattern);
  });
});
