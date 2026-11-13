import { describe, expect, it } from "vitest";

import { fqdnSuffixError, servicesWithInvalidSuffix } from "./fqdn-suffix";

describe("fqdnSuffixError", () => {
  it.each([
    "tailnet.example.ts.net",
    "internal",
    "my-tailnet.ts.net",
    "1.example.com",
    `${"a".repeat(63)}.example.com`,
    "",
    null,
    undefined,
  ])("accepts %j", (value) => {
    expect(fqdnSuffixError(value)).toBeNull();
  });

  it.each([
    ".example.com",
    "example.com.",
    "example..com",
    "Example.com",
    "exa_mple.com",
    "exa mple.com",
    "-bad.example.com",
    "bad-.example.com",
    `${"a".repeat(64)}.example.com`,
    `${"a".repeat(63)}.${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(62)}`,
    "example.com\n",
  ])("rejects %j with a message that names the rule", (value) => {
    expect(fqdnSuffixError(value)).toMatch(/DNS name/);
  });

  it("accepts 253 characters in total", () => {
    const value = `${"a".repeat(63)}.${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(61)}`;
    expect(value).toHaveLength(253);
    expect(fqdnSuffixError(value)).toBeNull();
  });
});

describe("servicesWithInvalidSuffix", () => {
  it("lists the services whose suffix is invalid", () => {
    expect(
      servicesWithInvalidSuffix([
        { name: "web", fqdnSuffix: "Bad.com" },
        { name: "api", fqdnSuffix: "ok.example.com" },
        { name: "task-manager", ingressClass: "x", fqdnSuffix: ".bad" },
        { name: "empty", fqdnSuffix: "" },
      ]),
    ).toEqual(["web", "task-manager"]);
  });

  it("returns nothing without rows", () => {
    expect(servicesWithInvalidSuffix(undefined)).toEqual([]);
    expect(servicesWithInvalidSuffix(null)).toEqual([]);
  });
});
