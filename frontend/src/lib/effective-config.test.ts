import { describe, expect, it } from "vitest";

import {
  computeEffectiveEnvVars,
  computeEffectiveServices,
  resolveConfigValue,
  type DeployedServiceRow,
} from "./effective-config";

describe("computeEffectiveEnvVars", () => {
  it("returns an empty list when all three layers are missing", () => {
    expect(computeEffectiveEnvVars(null, null, null)).toEqual([]);
    expect(computeEffectiveEnvVars(undefined, undefined, undefined)).toEqual(
      [],
    );
    expect(computeEffectiveEnvVars({}, {}, {})).toEqual([]);
  });

  it("attributes a cluster-only var to the cluster origin", () => {
    const result = computeEffectiveEnvVars(
      { env_vars: { CLUSTER_REGION: "us-east-1" } },
      null,
      null,
    );
    expect(result).toEqual([
      { name: "CLUSTER_REGION", value: "us-east-1", origin: "cluster" },
    ]);
  });

  it("environment values override cluster values at the same key", () => {
    const result = computeEffectiveEnvVars(
      { env_vars: { LOG_LEVEL: "info" } },
      { env_vars: { LOG_LEVEL: "debug" } },
      null,
    );
    expect(result).toEqual([
      { name: "LOG_LEVEL", value: "debug", origin: "environment" },
    ]);
  });

  it("deployment values override environment and cluster values", () => {
    const result = computeEffectiveEnvVars(
      { env_vars: { LOG_LEVEL: "info" } },
      { env_vars: { LOG_LEVEL: "debug" } },
      { env_vars: { LOG_LEVEL: "trace" } },
    );
    expect(result).toEqual([
      { name: "LOG_LEVEL", value: "trace", origin: "deployment" },
    ]);
  });

  it("preserves keys from every layer when they don't collide", () => {
    const result = computeEffectiveEnvVars(
      { env_vars: { CLUSTER_REGION: "us-east-1" } },
      { env_vars: { LOG_LEVEL: "info" } },
      { env_vars: { FEATURE_X: "on" } },
    );
    expect(result).toHaveLength(3);
    expect(result.find((e) => e.name === "CLUSTER_REGION")?.origin).toBe(
      "cluster",
    );
    expect(result.find((e) => e.name === "LOG_LEVEL")?.origin).toBe(
      "environment",
    );
    expect(result.find((e) => e.name === "FEATURE_X")?.origin).toBe(
      "deployment",
    );
  });

  it("orders deployment-defined first, then environment, then cluster (alphabetical within each)", () => {
    const result = computeEffectiveEnvVars(
      { env_vars: { CLUSTER_B: "1", CLUSTER_A: "1" } },
      { env_vars: { ENV_B: "1", ENV_A: "1" } },
      { env_vars: { DEP_B: "1", DEP_A: "1" } },
    );
    expect(result.map((e) => e.name)).toEqual([
      "DEP_A",
      "DEP_B",
      "ENV_A",
      "ENV_B",
      "CLUSTER_A",
      "CLUSTER_B",
    ]);
  });

  it("ignores non-object env_vars payloads defensively", () => {
    const result = computeEffectiveEnvVars(
      { env_vars: "not-an-object" as unknown as Record<string, string> },
      null,
      { env_vars: { OK: "1" } },
    );
    expect(result).toEqual([{ name: "OK", value: "1", origin: "deployment" }]);
  });
});

describe("computeEffectiveServices", () => {
  const baseRow: DeployedServiceRow = {
    id: "svc-1",
    driverServiceName: "api",
    resolvedName: "api",
    kind: "ClusterIP",
    port: 8080,
  };

  it("returns an empty list when the input is null/undefined", () => {
    expect(computeEffectiveServices(null)).toEqual([]);
    expect(computeEffectiveServices(undefined)).toEqual([]);
  });

  it("marks a service as not overridden when resolvedName matches driverServiceName", () => {
    const result = computeEffectiveServices([baseRow]);
    expect(result).toHaveLength(1);
    expect(result[0].isOverridden).toBe(false);
    expect(result[0].driverServiceName).toBe("api");
    expect(result[0].resolvedName).toBe("api");
  });

  it("marks a service as overridden when resolvedName differs from driverServiceName", () => {
    const result = computeEffectiveServices([
      { ...baseRow, resolvedName: "api-gateway-http" },
    ]);
    expect(result[0].isOverridden).toBe(true);
    expect(result[0].driverServiceName).toBe("api");
    expect(result[0].resolvedName).toBe("api-gateway-http");
  });

  it("passes through optional URLs and FQDNs verbatim", () => {
    const result = computeEffectiveServices([
      {
        ...baseRow,
        primaryUrl: "https://api.example.com",
        primaryFqdn: "api.example.com",
        humanReadableUrl: "https://api.example.com",
        humanReadableFqdn: "api.example.com",
      },
    ]);
    expect(result[0].primaryUrl).toBe("https://api.example.com");
    expect(result[0].primaryFqdn).toBe("api.example.com");
    expect(result[0].humanReadableUrl).toBe("https://api.example.com");
    expect(result[0].humanReadableFqdn).toBe("api.example.com");
  });
});

describe("resolveConfigValue", () => {
  it("returns { value: null, fromDeployment: false } when no layer defines the path", () => {
    expect(resolveConfigValue(null, null, null, "fqdn_suffix")).toEqual({
      value: null,
      fromDeployment: false,
    });
    expect(resolveConfigValue({}, {}, {}, "scheduling.runtime_class")).toEqual({
      value: null,
      fromDeployment: false,
    });
  });

  it("returns the cluster value with fromDeployment=false when only the cluster defines it", () => {
    const result = resolveConfigValue(
      { fqdn_suffix: "cluster.local" },
      null,
      null,
      "fqdn_suffix",
    );
    expect(result).toEqual({ value: "cluster.local", fromDeployment: false });
  });

  it("environment value wins over cluster value at the same path", () => {
    const result = resolveConfigValue(
      { ingress_class: "cluster-nginx" },
      { ingress_class: "env-nginx" },
      null,
      "ingress_class",
    );
    expect(result).toEqual({ value: "env-nginx", fromDeployment: false });
  });

  it("deployment value wins and fromDeployment is true even when same as env/cluster", () => {
    const result = resolveConfigValue(
      { ingress_class: "nginx" },
      { ingress_class: "nginx" },
      { ingress_class: "nginx" },
      "ingress_class",
    );
    expect(result).toEqual({ value: "nginx", fromDeployment: true });
  });

  it("walks nested snake_case paths through scheduling.resources", () => {
    const result = resolveConfigValue<string>(
      null,
      {
        scheduling: { resources: { requests: { cpu: "250m" } } },
      },
      {
        scheduling: { resources: { requests: { cpu: "500m" } } },
      },
      "scheduling.resources.requests.cpu",
    );
    expect(result).toEqual({ value: "500m", fromDeployment: true });
  });

  it("distinguishes explicit null at the deployment layer from absent", () => {
    // Explicit `null` at the deployment layer is still "defined" — the
    // operator wrote it, so fromDeployment is true and value is null.
    const result = resolveConfigValue(
      { fqdn_suffix: "cluster.local" },
      null,
      { fqdn_suffix: null },
      "fqdn_suffix",
    );
    expect(result).toEqual({ value: null, fromDeployment: true });
  });

  it("returns array values verbatim when the leaf is an array", () => {
    const result = resolveConfigValue<readonly string[]>(
      null,
      null,
      { ip_whitelist: ["10.0.0.0/8", "192.168.0.0/16"] },
      "ip_whitelist",
    );
    expect(result.value).toEqual(["10.0.0.0/8", "192.168.0.0/16"]);
    expect(result.fromDeployment).toBe(true);
  });
});
