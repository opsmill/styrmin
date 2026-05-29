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
          command: undefined,
          args: undefined,
        },
        { name: "api", envVars: [], command: undefined, args: undefined },
        {
          name: "worker",
          envVars: undefined,
          command: undefined,
          args: undefined,
        },
      ]),
    );
  });

  it("carries per-component command/args from the config block into the input", () => {
    // 014-component-container-overrides: a persisted component block may
    // carry `command`/`args` (list[str]) alongside `env_vars`. The
    // dict-to-list projection must surface them on the typed
    // `ComponentConfigInput` so the edit drawer renders the existing override.
    const input = deploymentConfigToInput({
      components: {
        web: {
          env_vars: { LOG_LEVEL: "debug" },
          command: ["/bin/sh", "-c"],
          args: ["echo", "hi"],
        },
      },
    });
    expect(input.components).toEqual([
      {
        name: "web",
        envVars: [{ name: "LOG_LEVEL", value: "debug" }],
        command: ["/bin/sh", "-c"],
        args: ["echo", "hi"],
      },
    ]);
  });

  it("maps a null command/args block to undefined (omit = clear, never [])", () => {
    // 014-component-container-overrides / FR-007: a persisted `null` (or
    // absent) container override stays `undefined` on the input so a
    // full-replacement write omits the field rather than sending `[]`
    // (the backend rejects `[]` with INVALID_CONTAINER_COMMAND / _ARGS).
    const input = deploymentConfigToInput({
      components: {
        web: { env_vars: {}, command: null, args: null },
        api: { env_vars: {} },
      },
    });
    expect(input.components).toEqual(
      expect.arrayContaining([
        { name: "web", envVars: [], command: undefined, args: undefined },
        { name: "api", envVars: [], command: undefined, args: undefined },
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
      {
        name: "web",
        envVars: [{ name: "COMP", value: "2" }],
        command: undefined,
        args: undefined,
      },
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

  it("renames scheduling.inject snake_case keys to camelCase", () => {
    // Regression: the persisted ``PostRenderInjection`` Pydantic model uses
    // snake_case (``node_affinity``, ``pod_affinity``, ``topology_spread``,
    // ``runtime_class``). Without conversion, those keys leak into the form
    // state; when the user toggles a checkbox the form writes the camelCase
    // sibling and Strawberry rejects the dual-key payload with
    // "Field 'node_affinity' is not defined by type 'PostRenderInjectionInput'".
    const input = deploymentConfigToInput({
      scheduling: {
        inject: {
          node_affinity: true,
          pod_affinity: false,
          topology_spread: true,
          runtime_class: false,
          resources: true,
          tolerations: false,
        },
      },
    });
    expect(input.scheduling?.inject).toEqual({
      nodeAffinity: true,
      podAffinity: false,
      topologySpread: true,
      runtimeClass: false,
      resources: true,
      tolerations: false,
    });
    // Guard against the dual-key payload — no snake_case key may survive.
    const injectKeys = Object.keys(input.scheduling?.inject ?? {});
    expect(injectKeys.filter((k) => k.includes("_"))).toEqual([]);
  });

  it("renames the top-level scheduling.pod_affinity block to podAffinity", () => {
    // Regression: ``node_affinity`` and ``pod_anti_affinity`` had explicit
    // rename branches but ``pod_affinity`` did not, leaving the snake_case
    // block in the form state.
    const input = deploymentConfigToInput({
      scheduling: {
        pod_affinity: {
          required: [
            {
              topology_key: "kubernetes.io/hostname",
              label_selector: { match_labels: { app: "web" } },
            },
          ],
        },
      },
    });
    expect(input.scheduling).not.toHaveProperty("pod_affinity");
    expect(input.scheduling?.podAffinity).toBeDefined();
    expect(input.scheduling?.podAffinity?.required?.[0]).toMatchObject({
      topologyKey: "kubernetes.io/hostname",
      labelSelector: { matchLabels: { app: "web" } },
    });
  });

  it("normalizes nested affinity term keys to camelCase end-to-end", () => {
    // Regression: ``topology_key``, ``match_label_keys``, ``mismatch_label_keys``,
    // ``deployment_ref`` were not renamed inside affinity terms; and
    // ``normalizeLabelSelector`` left ``match_expressions`` next to its
    // camelCase sibling (the spread did not delete the snake key), producing
    // the duplicate ``match_expressions``/``matchExpressions`` pair visible
    // in the "Review configuration changes" diff.
    const input = deploymentConfigToInput({
      scheduling: {
        node_affinity: {
          required: [
            {
              topology_key: "",
              match_label_keys: ["a"],
              mismatch_label_keys: ["b"],
              deployment_ref: { deployment_name: "peer" },
              label_selector: {
                match_labels: { tier: "data" },
                match_expressions: [
                  { key: "role", operator: "In", values: ["data"] },
                ],
              },
              namespace_selector: {
                match_expressions: [
                  { key: "team", operator: "NotIn", values: ["ops"] },
                ],
              },
            },
          ],
        },
      },
    });
    const term = input.scheduling?.nodeAffinity?.required?.[0] as Record<
      string,
      unknown
    >;
    expect(term).toBeDefined();
    expect(term).toMatchObject({
      topologyKey: "",
      matchLabelKeys: ["a"],
      mismatchLabelKeys: ["b"],
      deploymentRef: { deployment_name: "peer" },
      labelSelector: {
        matchLabels: { tier: "data" },
        matchExpressions: [{ key: "role", operator: "IN", values: ["data"] }],
      },
      namespaceSelector: {
        matchExpressions: [
          { key: "team", operator: "NOT_IN", values: ["ops"] },
        ],
      },
    });
    // No snake_case key may survive on the term, the labelSelector, or the
    // namespaceSelector.
    const allKeys = [
      ...Object.keys(term),
      ...Object.keys(term.labelSelector as Record<string, unknown>),
      ...Object.keys(term.namespaceSelector as Record<string, unknown>),
    ];
    expect(allKeys.filter((k) => k.includes("_"))).toEqual([]);
  });

  it("normalizes topology_spread_constraints row keys to camelCase", () => {
    // Regression: only ``when_unsatisfiable`` and ``label_selector`` were
    // renamed on each row; ``max_skew``, ``topology_key``, ``min_domains``,
    // ``node_affinity_policy``, ``node_taints_policy``, and ``match_label_keys``
    // leaked through.
    const input = deploymentConfigToInput({
      scheduling: {
        topology_spread_constraints: [
          {
            max_skew: 1,
            topology_key: "kubernetes.io/hostname",
            when_unsatisfiable: "DoNotSchedule",
            min_domains: 2,
            node_affinity_policy: "Honor",
            node_taints_policy: "Ignore",
            match_label_keys: ["x"],
            label_selector: { match_labels: { app: "web" } },
          },
        ],
      },
    });
    const row = input.scheduling?.topologySpreadConstraints?.[0] as Record<
      string,
      unknown
    >;
    expect(row).toBeDefined();
    expect(row).toMatchObject({
      maxSkew: 1,
      topologyKey: "kubernetes.io/hostname",
      whenUnsatisfiable: "DO_NOT_SCHEDULE",
      minDomains: 2,
      nodeAffinityPolicy: "Honor",
      nodeTaintsPolicy: "Ignore",
      matchLabelKeys: ["x"],
      labelSelector: { matchLabels: { app: "web" } },
    });
    expect(Object.keys(row).filter((k) => k.includes("_"))).toEqual([]);
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
