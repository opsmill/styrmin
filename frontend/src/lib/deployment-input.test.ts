import { describe, it, expect } from "vitest";
import { deploymentConfigToInput } from "./deployment-input";

describe("deploymentConfigToInput", () => {
  it("converts an empty config into an input with every field undefined", () => {
    const input = deploymentConfigToInput({});
    // Every UpdateDeploymentInput field this helper populates must be
    // undefined when the source config has no corresponding key. The
    // resolver treats `null`/missing as "do not touch", so undefined here
    // is the correct shape — anything else (e.g. `[]` for envVars) would
    // explicitly clear the persisted state.
    expect(input).toEqual({
      envVars: undefined,
      components: undefined,
      ipWhitelist: undefined,
      dedicatedIngress: undefined,
      scheduling: undefined,
      fqdnSuffix: undefined,
      externalUrlScheme: undefined,
      externalUrlPort: undefined,
      externalDnsEndpointsType: undefined,
      ingressClass: undefined,
      dbSize: undefined,
      runtimeClass: undefined,
      nodeSelector: undefined,
      standardStorage: undefined,
    });
  });

  it("translates the env_vars dict into a list of {name, value} rows", () => {
    const input = deploymentConfigToInput({
      env_vars: { FOO: "bar", BAZ: "qux" },
    });
    expect(input.envVars).toHaveLength(2);
    expect(input.envVars).toEqual(
      expect.arrayContaining([
        { name: "FOO", value: "bar" },
        { name: "BAZ", value: "qux" },
      ]),
    );
  });

  it("yields an empty envVars list (not undefined) when env_vars is an empty dict", () => {
    // An explicit empty dict in the read-side config corresponds to "the
    // user wants the persisted env-var list cleared", which the typed
    // input expresses as an empty list. Distinguishing this from "field
    // omitted" (undefined) is the whole point of the dict-to-list
    // translation.
    const input = deploymentConfigToInput({ env_vars: {} });
    expect(input.envVars).toEqual([]);
  });

  it("translates the components dict into a list with per-component envVars", () => {
    const input = deploymentConfigToInput({
      components: {
        web: { env_vars: { LOG_LEVEL: "debug" } },
        api: { env_vars: {} },
        worker: { env_vars: null },
      },
    });
    expect(input.components).toHaveLength(3);
    expect(input.components).toEqual(
      expect.arrayContaining([
        {
          name: "web",
          envVars: [{ name: "LOG_LEVEL", value: "debug" }],
        },
        { name: "api", envVars: [] },
        { name: "worker", envVars: undefined },
      ]),
    );
  });

  it("preserves every other field unchanged from a fully-populated config", () => {
    const fullConfig = {
      env_vars: { GLOBAL: "1" },
      components: { web: { env_vars: { COMP: "2" } } },
      ip_whitelist: ["10.0.0.0/8", "192.168.0.0/16"],
      dedicated_ingress: { enabled: true, replicas: 2 },
      scheduling: { runtimeClass: "kata-e2e" },
      fqdn_suffix: ".prod.example.com",
      external_url_scheme: "HTTPS",
      external_url_port: 8443,
      external_dns_endpoints_type: "INGRESS",
      ingress_class: "nginx",
      db_size: "100Gi",
      runtime_class: "kata-e2e",
      node_selector: "topology.kubernetes.io/zone=us-east-1a",
      standard_storage: { className: "gp3", size: "50Gi" },
    };

    const input = deploymentConfigToInput(fullConfig);

    expect(input.envVars).toEqual([{ name: "GLOBAL", value: "1" }]);
    expect(input.components).toEqual([
      { name: "web", envVars: [{ name: "COMP", value: "2" }] },
    ]);
    expect(input.ipWhitelist).toEqual(["10.0.0.0/8", "192.168.0.0/16"]);
    expect(input.dedicatedIngress).toEqual({ enabled: true, replicas: 2 });
    expect(input.scheduling).toEqual({ runtimeClass: "kata-e2e" });
    expect(input.fqdnSuffix).toBe(".prod.example.com");
    expect(input.externalUrlScheme).toBe("HTTPS");
    expect(input.externalUrlPort).toBe(8443);
    expect(input.externalDnsEndpointsType).toBe("INGRESS");
    expect(input.ingressClass).toBe("nginx");
    expect(input.dbSize).toBe("100Gi");
    expect(input.runtimeClass).toBe("kata-e2e");
    expect(input.nodeSelector).toBe("topology.kubernetes.io/zone=us-east-1a");
    expect(input.standardStorage).toEqual({ className: "gp3", size: "50Gi" });
  });

  it("ignores unknown keys on the source config", () => {
    // The JSDoc on `deploymentConfigToInput` documents that unknown keys
    // are dropped silently — guard against accidental reintroduction of
    // an unsafe spread that would surface them in the typed input.
    const input = deploymentConfigToInput({
      env_vars: { A: "1" },
      something_unknown: "stay-out",
      another_extra: { nested: true },
    });
    expect(input).not.toHaveProperty("something_unknown");
    expect(input).not.toHaveProperty("another_extra");
    expect(input.envVars).toEqual([{ name: "A", value: "1" }]);
  });

  it("translates scheduling enum values from K8s casing to GraphQL identifiers", () => {
    // The persisted config stores enum *values* (K8s-native casing — e.g.
    // ``operator: "Equal"``) but ``UpdateDeploymentInput`` requires the
    // GraphQL enum *identifier* (``"EQUAL"``). Without this translation,
    // re-submitting an unchanged toleration sends ``"Equal"`` and the
    // ``updateDeployment`` mutation fails with a Strawberry enum validation
    // error. Regression coverage for the bug that surfaced in
    // ``test_drawer_disruptive_toleration_effect_change``.
    const input = deploymentConfigToInput({
      scheduling: {
        tolerations: [
          {
            key: "dedicated",
            operator: "Equal",
            value: "batch",
            effect: "PreferNoSchedule",
          },
        ],
      },
      external_url_scheme: "https",
      external_dns_endpoints_type: "NodeExternalIP",
    });
    expect(input.scheduling?.tolerations?.[0]).toMatchObject({
      key: "dedicated",
      operator: "EQUAL",
      value: "batch",
      effect: "PREFER_NO_SCHEDULE",
    });
    expect(input.externalUrlScheme).toBe("HTTPS");
    expect(input.externalDnsEndpointsType).toBe("NODE_EXTERNAL_IP");
  });
});
