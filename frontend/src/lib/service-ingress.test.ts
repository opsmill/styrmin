import { describe, expect, it } from "vitest";

import { getsIngress } from "./service-ingress";

describe("getsIngress", () => {
  it.each(["http", "https"])("is true for an external %s service", (kind) => {
    expect(getsIngress({ scope: "external", kind })).toBe(true);
  });

  it.each(["tcp", "udp"])("is false for an external %s service", (kind) => {
    expect(getsIngress({ scope: "external", kind })).toBe(false);
  });

  it.each(["http", "https", "tcp", "udp"])(
    "is false for an internal %s service",
    (kind) => {
      expect(getsIngress({ scope: "internal", kind })).toBe(false);
    },
  );
});
