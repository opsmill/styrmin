import { describe, it, expect } from "vitest";
import { networkingSchema } from "./NetworkingSection";

describe("networkingSchema", () => {
  it("accepts a valid networking block", () => {
    const result = networkingSchema.safeParse({
      fqdnSuffix: "example.com",
      externalUrlScheme: "HTTPS",
      externalUrlPort: 443,
      externalDnsEndpointsType: "CLUSTER_IP",
      ingressClass: "nginx",
      dedicatedIngress: { type: "LoadBalancer", implementation: "nginx" },
      ipWhitelist: ["10.0.0.0/8", "2001:db8::/32"],
    });
    expect(result.success).toBe(true);
  });

  it("rejects an out-of-range external URL port", () => {
    const result = networkingSchema.safeParse({ externalUrlPort: 99999 });
    expect(result.success).toBe(false);
  });

  it("rejects an invalid CIDR in the allowlist", () => {
    const result = networkingSchema.safeParse({
      ipWhitelist: ["not-a-cidr"],
    });
    expect(result.success).toBe(false);
  });
});
