import { describe, it, expect } from "vitest";
import type { ServiceConfigInput } from "@/generated/graphql";
import {
  componentsFormToInput,
  deploymentConfigToInput,
} from "./deployment-input";
import * as deploymentInput from "./deployment-input";

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
      standardStorage: undefined,
      fastStorage: undefined,
      backupTtl: undefined,
    });
  });

  it("carries backup_ttl through to backupTtl", () => {
    // 016 / FR-005: the full-replacement update builders assemble their
    // input from the persisted config, so a deployment-scope retention
    // override that this projection drops would be silently wiped by the
    // next unrelated save.
    const input = deploymentConfigToInput({ backup_ttl: "8760h" });
    expect(input.backupTtl).toBe("8760h");
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

  it("carries a per-component image from the config block into the input", () => {
    // 018-component-image-overrides: the stored reference (tokens included)
    // surfaces on `ComponentConfigInput.image` so the drawer pre-fills it.
    const input = deploymentConfigToInput({
      components: {
        server: { image: "registry.example/acme/app:{{ app.version }}" },
        worker: { env_vars: {}, image: null },
      },
    });
    expect(input.components).toEqual([
      {
        name: "server",
        envVars: undefined,
        command: undefined,
        args: undefined,
        image: "registry.example/acme/app:{{ app.version }}",
      },
      { name: "worker", envVars: [], command: undefined, args: undefined },
    ]);
  });

  it("carries a per-component replica override from the config block into the input", () => {
    const input = deploymentConfigToInput({
      components: {
        server: { replicas: 3 },
        worker: { env_vars: {}, replicas: null },
      },
    });
    expect(input.components).toEqual([
      {
        name: "server",
        envVars: undefined,
        command: undefined,
        args: undefined,
        replicas: 3,
      },
      { name: "worker", envVars: [], command: undefined, args: undefined },
    ]);
    expect(input.components?.[1]?.replicas).toBeUndefined();
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
              deployment_ref: {
                deployment_id: "11111111-1111-1111-1111-111111111111",
                deployment_name: "peer",
                components: ["db"],
              },
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
      deploymentRef: {
        deploymentId: "11111111-1111-1111-1111-111111111111",
        deploymentName: "peer",
        components: ["db"],
      },
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
      ...Object.keys(term.deploymentRef as Record<string, unknown>),
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

  it("renames scheduling.resources ephemeral_storage to ephemeralStorage", () => {
    const input = deploymentConfigToInput({
      scheduling: {
        resources: {
          requests: { cpu: "100m", ephemeral_storage: "1Gi" },
          limits: {
            ephemeral_storage: "2Gi",
            extended: { "nvidia.com/gpu": "1" },
          },
        },
      },
    });
    expect(input.scheduling?.resources).toEqual({
      requests: { cpu: "100m", ephemeralStorage: "1Gi" },
      limits: { ephemeralStorage: "2Gi", extended: { "nvidia.com/gpu": "1" } },
    });
  });
});

describe("componentsFormToInput", () => {
  it("passes undefined and null through", () => {
    expect(componentsFormToInput(undefined)).toBeUndefined();
    expect(componentsFormToInput(null)).toBeNull();
  });

  it("maps an empty image field to image: null (clear)", () => {
    expect(
      componentsFormToInput([{ name: "server", envVars: [], image: "" }]),
    ).toEqual([{ name: "server", envVars: [], image: null }]);
  });

  it("keeps a set image and leaves an untouched one absent", () => {
    const out = componentsFormToInput([
      { name: "server", envVars: [], image: "app:1" },
      { name: "worker", envVars: [] },
    ]);
    expect(out).toEqual([
      { name: "server", envVars: [], image: "app:1" },
      { name: "worker", envVars: [] },
    ]);
    expect(out?.[1]).not.toHaveProperty("image");
  });

  it("omits empty command/args lists but keeps an empty envVars list", () => {
    // FR-007 (014): omit = clear for command/args, the backend rejects [];
    // `envVars: []` is a legitimate clear and passes through.
    expect(
      componentsFormToInput([
        { name: "server", envVars: [], command: [], args: [] },
        { name: "worker", command: ["/bin/sh"], args: ["-c"] },
      ]),
    ).toEqual([
      { name: "server", envVars: [] },
      { name: "worker", command: ["/bin/sh"], args: ["-c"] },
    ]);
  });

  it("maps an empty or unparseable replicas field to replicas: null (clear)", () => {
    expect(
      componentsFormToInput([
        { name: "server", replicas: "" as unknown as number },
        { name: "worker", replicas: Number.NaN },
      ]),
    ).toEqual([
      { name: "server", replicas: null },
      { name: "worker", replicas: null },
    ]);
  });

  it("keeps a set replica count, a cleared one and leaves an untouched one absent", () => {
    const out = componentsFormToInput([
      { name: "server", envVars: [], replicas: 2 },
      { name: "migrate", replicas: null },
      { name: "worker", envVars: [] },
    ]);
    expect(out).toEqual([
      { name: "server", envVars: [], replicas: 2 },
      { name: "migrate", replicas: null },
      { name: "worker", envVars: [] },
    ]);
    expect(out?.[1]?.replicas).toBeNull();
    expect(out?.[2]).not.toHaveProperty("replicas");
  });

  it("round-trips image read -> form -> ComponentConfigInput", () => {
    const form = deploymentConfigToInput({
      components: {
        server: {
          env_vars: { LOG_LEVEL: "debug" },
          image: "registry.example/acme/app-patched:{{ app.version }}",
        },
      },
    }).components;
    expect(componentsFormToInput(form)).toEqual([
      {
        name: "server",
        envVars: [{ name: "LOG_LEVEL", value: "debug" }],
        image: "registry.example/acme/app-patched:{{ app.version }}",
      },
    ]);

    // Clearing the field in the drawer submits an explicit null.
    const cleared = form!.map((block) => ({ ...block, image: "" }));
    expect(componentsFormToInput(cleared)?.[0].image).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Service ingress overrides (#598, US3, T046). The stored config holds
// `services` as a dict keyed by driver service name; `UpdateDeploymentInput`
// takes a list of rows. `updateDeployment` replaces the whole stored config, so
// a projection that leaves `services` out clears every stored override on the
// next save of any other field (T030a reproduced this for the SDK `scale`).
// ---------------------------------------------------------------------------

describe("deploymentConfigToInput: services", () => {
  it("leaves services undefined when the config stores none", () => {
    expect(deploymentConfigToInput({}).services).toBeUndefined();
  });

  it("projects the stored dict onto a list of rows keyed by service name", () => {
    const input = deploymentConfigToInput({
      services: {
        "task-manager": {
          ingress_class: "tailscale",
          fqdn_suffix: "tailnet.example.ts.net",
        },
        web: { ingress_class: "traefik", fqdn_suffix: null },
      },
    });

    expect(input.services).toEqual([
      {
        name: "task-manager",
        ingressClass: "tailscale",
        fqdnSuffix: "tailnet.example.ts.net",
      },
      { name: "web", ingressClass: "traefik" },
    ]);
    // A stored null is no override: the row carries no key for it.
    expect(input.services?.[1]).not.toHaveProperty("fqdnSuffix");
  });
});

/**
 * `servicesFormToInput` is the submit boundary for the service rows, as
 * `componentsFormToInput` is for the component blocks. It is read from the
 * module namespace so that this file type-checks before T046 adds the export;
 * until then each test below fails with the error thrown here. T046 may switch
 * to a named import.
 */
const servicesFormToInput: (
  rows: readonly ServiceConfigInput[] | null | undefined,
) => ServiceConfigInput[] | null | undefined =
  (
    deploymentInput as unknown as {
      servicesFormToInput?: (
        rows: readonly ServiceConfigInput[] | null | undefined,
      ) => ServiceConfigInput[] | null | undefined;
    }
  ).servicesFormToInput ??
  (() => {
    throw new Error(
      "servicesFormToInput is not exported by lib/deployment-input.ts (T046)",
    );
  });

describe("servicesFormToInput", () => {
  it("passes undefined and null through", () => {
    expect(servicesFormToInput(undefined)).toBeUndefined();
    expect(servicesFormToInput(null)).toBeNull();
  });

  it("keeps a row that sets both fields", () => {
    const row = {
      name: "task-manager",
      ingressClass: "tailscale",
      fqdnSuffix: "tailnet.example.ts.net",
    };
    expect(servicesFormToInput([row])).toEqual([row]);
  });

  it("omits an emptied field: the backend rejects an empty ingress class and an empty suffix", () => {
    // An emptied input holds "". Under full replacement, omitting the field
    // clears it (contract: null or omitted means the resolved value applies).
    const out = servicesFormToInput([
      {
        name: "task-manager",
        ingressClass: "",
        fqdnSuffix: "tailnet.example.ts.net",
      },
      { name: "web", ingressClass: "traefik", fqdnSuffix: "" },
    ]);

    expect(out).toEqual([
      { name: "task-manager", fqdnSuffix: "tailnet.example.ts.net" },
      { name: "web", ingressClass: "traefik" },
    ]);
    expect(out?.[0]).not.toHaveProperty("ingressClass");
    expect(out?.[1]).not.toHaveProperty("fqdnSuffix");
  });

  it("drops a row with no value: it is no override", () => {
    expect(
      servicesFormToInput([
        { name: "task-manager", ingressClass: "", fqdnSuffix: "" },
        { name: "web", ingressClass: null, fqdnSuffix: null },
        { name: "worker" },
        { name: "api", ingressClass: "traefik" },
      ]),
    ).toEqual([{ name: "api", ingressClass: "traefik" }]);
  });

  it("round-trips stored config -> form -> submitted rows", () => {
    const form = deploymentConfigToInput({
      services: {
        "task-manager": {
          ingress_class: "tailscale",
          fqdn_suffix: "tailnet.example.ts.net",
        },
      },
    }).services;

    expect(servicesFormToInput(form)).toEqual([
      {
        name: "task-manager",
        ingressClass: "tailscale",
        fqdnSuffix: "tailnet.example.ts.net",
      },
    ]);
  });
});
