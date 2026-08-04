import { describe, it, expect } from "vitest";
import { render, screen, within } from "@/test/utils";
import EnvironmentConfigurationTab from "@/pages/environments/EnvironmentConfigurationTab";
import {
  EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
  EXTERNAL_URL_SCHEME_MAP,
  buildFullReplacementInput,
  transformEnumValue,
} from "@/pages/environments/EnvironmentConfigurationTab.helpers";

const ENV_ID = "00000000-0000-0000-0000-000000000001";

const noDeployments: Array<{ id: string; name: string; internal: boolean }> =
  [];

describe("EnvironmentConfigurationTab", () => {
  it("renders all six sections with populated values", async () => {
    const config: Record<string, unknown> = {
      env_vars: {
        OTEL_EXPORTER_OTLP_ENDPOINT: "https://otel.staging",
        LOG_LEVEL: "debug",
      },
      backup_ttl: "2160h",
      ip_whitelist: ["10.0.0.0/8", "192.168.0.0/16"],
      dedicated_ingress: {
        class_name: "nginx-staging",
        hostname_override: "ingress.staging.example.com",
      },
      scheduling: {
        runtime_class: "kata",
      },
      fqdn_suffix: "fqdn.staging.example.com",
      external_url_scheme: "HTTPS",
      external_url_port: 443,
      external_dns_endpoints_type: "INGRESS",
    };

    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={config}
        deployments={noDeployments}
      />,
    );

    // Every section card is present.
    expect(screen.getByTestId("section-env-vars")).toBeInTheDocument();
    expect(screen.getByTestId("section-backup-retention")).toBeInTheDocument();
    expect(screen.getByTestId("section-ip-allowlist")).toBeInTheDocument();
    expect(screen.getByTestId("section-dedicated-ingress")).toBeInTheDocument();
    expect(screen.getByTestId("section-scheduling")).toBeInTheDocument();
    expect(screen.getByTestId("section-fqdn")).toBeInTheDocument();

    // Env vars rendered through the editable form (Phase 6 / US4).
    const formRows = screen.getByTestId("env-vars-form-rows");
    const nameInputs = within(formRows).getAllByTestId("env-var-name-input");
    const valueInputs = within(formRows).getAllByTestId("env-var-value-input");
    const namesAndValues = nameInputs.map((input, idx) => ({
      name: (input as HTMLInputElement).value,
      value: (valueInputs[idx] as HTMLInputElement).value,
    }));
    expect(namesAndValues).toEqual(
      expect.arrayContaining([
        {
          name: "OTEL_EXPORTER_OTLP_ENDPOINT",
          value: "https://otel.staging",
        },
        { name: "LOG_LEVEL", value: "debug" },
      ]),
    );

    // IP allowlist.
    const ipList = screen.getByTestId("ip-allowlist-list");
    expect(within(ipList).getByText("10.0.0.0/8")).toBeInTheDocument();
    expect(within(ipList).getByText("192.168.0.0/16")).toBeInTheDocument();

    // Dedicated ingress + scheduling values appear somewhere on the page.
    expect(screen.getByText("nginx-staging")).toBeInTheDocument();
    expect(screen.getByText("ingress.staging.example.com")).toBeInTheDocument();
    expect(screen.getByText("fqdn.staging.example.com")).toBeInTheDocument();
    expect(screen.getByText("kata")).toBeInTheDocument();

    // FQDN settings.
    expect(screen.getByText("HTTPS")).toBeInTheDocument();
    expect(screen.getByText("443")).toBeInTheDocument();
    expect(screen.getByText("INGRESS")).toBeInTheDocument();

    // Backup retention is seeded from the persisted policy (016).
    expect(
      (screen.getByTestId("backup-retention-input") as HTMLInputElement).value,
    ).toBe("2160h");

    // No empty-state messages should render when every section is populated.
    expect(screen.queryAllByTestId("empty-section-message")).toHaveLength(0);
  });

  it("renders empty-state messages for a fully-empty config", async () => {
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={{}}
        deployments={noDeployments}
      />,
    );

    expect(screen.getByTestId("env-vars-form-empty")).toBeInTheDocument();
    expect(screen.getByText("No IP allowlist configured.")).toBeInTheDocument();
    expect(
      screen.getByText("Using default ingress controller."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No scheduling overrides set."),
    ).toBeInTheDocument();
    expect(screen.getByText("Using cluster defaults.")).toBeInTheDocument();

    // No populated lists.
    expect(screen.queryByTestId("env-vars-form-rows")).toBeNull();
    expect(screen.queryByTestId("ip-allowlist-list")).toBeNull();

    // Retention: blank input, and the inherited notice instead of a value
    // — the section stays informative when the environment sets no policy.
    expect(
      (screen.getByTestId("backup-retention-input") as HTMLInputElement).value,
    ).toBe("");
    expect(screen.getByTestId("backup-retention-current")).toHaveTextContent(
      /no environment policy set/i,
    );
  });

  it("does not crash on a partially-populated config (env_vars only)", async () => {
    const config: Record<string, unknown> = {
      env_vars: { ONLY_ONE: "yes" },
    };

    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={config}
        deployments={noDeployments}
      />,
    );

    // The populated section renders its row in the editable form.
    const formRows = screen.getByTestId("env-vars-form-rows");
    const nameInputs = within(formRows).getAllByTestId("env-var-name-input");
    const valueInputs = within(formRows).getAllByTestId("env-var-value-input");
    expect(nameInputs).toHaveLength(1);
    expect((nameInputs[0] as HTMLInputElement).value).toBe("ONLY_ONE");
    expect((valueInputs[0] as HTMLInputElement).value).toBe("yes");

    // Every other section falls back to its empty-state message.
    expect(screen.getByText("No IP allowlist configured.")).toBeInTheDocument();
    expect(
      screen.getByText("Using default ingress controller."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No scheduling overrides set."),
    ).toBeInTheDocument();
    expect(screen.getByText("Using cluster defaults.")).toBeInTheDocument();
  });

  it("treats null config as fully empty without crashing", async () => {
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={null}
        deployments={noDeployments}
      />,
    );
    expect(
      screen.getByTestId("environment-configuration-tab"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("env-vars-form-empty")).toBeInTheDocument();
  });

  // Regression: review H2. ``buildFullReplacementInput`` ships nested
  // fields as ``null`` because the v1 form cannot map
  // ``DedicatedIngressInput`` / ``SchedulingInput``. To prevent a
  // silent clear under full-replacement semantics, the section detects
  // nested overrides on the persisted config and blocks submission.
  it("blocks Save when dedicated_ingress is set on the persisted config", async () => {
    const config: Record<string, unknown> = {
      env_vars: { LOG_LEVEL: "info" },
      dedicated_ingress: {
        class_name: "nginx-staging",
      },
    };
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={config}
        deployments={noDeployments}
      />,
    );
    expect(
      screen.getByTestId("env-vars-form-blocked-warning"),
    ).toHaveTextContent(/dedicated_ingress/i);
    expect(screen.getByTestId("env-vars-form-save-button")).toBeDisabled();
  });

  it("blocks Save when scheduling is set on the persisted config", async () => {
    const config: Record<string, unknown> = {
      env_vars: { LOG_LEVEL: "info" },
      scheduling: {
        runtime_class: "kata",
      },
    };
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={config}
        deployments={noDeployments}
      />,
    );
    expect(
      screen.getByTestId("env-vars-form-blocked-warning"),
    ).toHaveTextContent(/scheduling/i);
    expect(screen.getByTestId("env-vars-form-save-button")).toBeDisabled();
  });

  it("does not block Save when neither nested override is set", async () => {
    const config: Record<string, unknown> = {
      env_vars: { LOG_LEVEL: "info" },
      ip_whitelist: ["10.0.0.0/8"],
    };
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={config}
        deployments={noDeployments}
      />,
    );
    expect(
      screen.queryByTestId("env-vars-form-blocked-warning"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("env-vars-form-save-button")).toBeEnabled();
  });

  // 011/US2: post-011, ingress_class and db_size are carried through
  // buildFullReplacementInput unchanged. They no longer trip the H2
  // block (they never did pre-011 either — they were silently cleared,
  // which is the bug 011 fixes), so a config with these fields set
  // and no nested overrides is safe to submit.
  it("does not block Save when ingress_class / db_size are set (011/US2)", async () => {
    const config: Record<string, unknown> = {
      env_vars: { LOG_LEVEL: "info" },
      ingress_class: "nginx",
      db_size: "10Gi",
    };
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={config}
        deployments={noDeployments}
      />,
    );
    expect(
      screen.queryByTestId("env-vars-form-blocked-warning"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("env-vars-form-save-button")).toBeEnabled();
  });
});

// ---------------------------------------------------------------------------
// 011/US2 — transformEnumValue + buildFullReplacementInput unit tests
// ---------------------------------------------------------------------------

describe("transformEnumValue (011/US2)", () => {
  it("maps 'http' to 'HTTP'", () => {
    expect(transformEnumValue("scheme", "http", EXTERNAL_URL_SCHEME_MAP)).toBe(
      "HTTP",
    );
  });

  it("maps 'https' to 'HTTPS'", () => {
    expect(transformEnumValue("scheme", "https", EXTERNAL_URL_SCHEME_MAP)).toBe(
      "HTTPS",
    );
  });

  it("maps 'NodeExternalIP' to 'NODE_EXTERNAL_IP'", () => {
    expect(
      transformEnumValue(
        "endpointsType",
        "NodeExternalIP",
        EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
      ),
    ).toBe("NODE_EXTERNAL_IP");
  });

  it("maps 'ClusterIP' to 'CLUSTER_IP'", () => {
    expect(
      transformEnumValue(
        "endpointsType",
        "ClusterIP",
        EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
      ),
    ).toBe("CLUSTER_IP");
  });

  it("returns null for null input", () => {
    expect(
      transformEnumValue("scheme", null, EXTERNAL_URL_SCHEME_MAP),
    ).toBeNull();
    expect(
      transformEnumValue(
        "endpointsType",
        null,
        EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
      ),
    ).toBeNull();
  });

  it("returns null for undefined input", () => {
    expect(
      transformEnumValue("scheme", undefined, EXTERNAL_URL_SCHEME_MAP),
    ).toBeNull();
    expect(
      transformEnumValue(
        "endpointsType",
        undefined,
        EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
      ),
    ).toBeNull();
  });

  it("throws on unrecognised scheme value with field name + value in message", () => {
    expect(() =>
      transformEnumValue("externalUrlScheme", "wss", EXTERNAL_URL_SCHEME_MAP),
    ).toThrow(/externalUrlScheme.*wss/);
  });

  it("throws on unrecognised endpoints type value with field name + value in message", () => {
    expect(() =>
      transformEnumValue(
        "externalDnsEndpointsType",
        "InternalIP",
        EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
      ),
    ).toThrow(/externalDnsEndpointsType.*InternalIP/);
  });

  it("throws on non-string non-null value with type info in message", () => {
    expect(() =>
      transformEnumValue("scheme", 42, EXTERNAL_URL_SCHEME_MAP),
    ).toThrow(/expected string, got number/);
  });
});

describe("buildFullReplacementInput (011/US2)", () => {
  it("transforms enum strings and carries through ingress_class + db_size", () => {
    const config: Record<string, unknown> = {
      env_vars: { LOG_LEVEL: "info" },
      ip_whitelist: ["10.0.0.0/8"],
      fqdn_suffix: "staging.example.com",
      external_url_scheme: "https",
      external_url_port: 443,
      external_dns_endpoints_type: "NodeExternalIP",
      ingress_class: "nginx",
      db_size: "10Gi",
    };
    const input = buildFullReplacementInput(config, [
      { name: "LOG_LEVEL", value: "debug" },
    ]);
    expect(input).toEqual({
      envVars: [{ name: "LOG_LEVEL", value: "debug" }],
      ipWhitelist: ["10.0.0.0/8"],
      fqdnSuffix: "staging.example.com",
      externalUrlScheme: "HTTPS",
      externalUrlPort: 443,
      externalDnsEndpointsType: "NODE_EXTERNAL_IP",
      ingressClass: "nginx",
      dbSize: "10Gi",
      backupTtl: null,
      dedicatedIngress: null,
      scheduling: null,
    });
  });

  it("maps 'http' + 'ClusterIP' to their literals", () => {
    const config: Record<string, unknown> = {
      external_url_scheme: "http",
      external_dns_endpoints_type: "ClusterIP",
    };
    const input = buildFullReplacementInput(config, []);
    expect(input.externalUrlScheme).toBe("HTTP");
    expect(input.externalDnsEndpointsType).toBe("CLUSTER_IP");
  });

  it("emits null for unset enum + scalar fields", () => {
    const input = buildFullReplacementInput({}, []);
    expect(input).toEqual({
      envVars: [],
      ipWhitelist: null,
      fqdnSuffix: null,
      externalUrlScheme: null,
      externalUrlPort: null,
      externalDnsEndpointsType: null,
      ingressClass: null,
      dbSize: null,
      backupTtl: null,
      dedicatedIngress: null,
      scheduling: null,
    });
  });

  it("emits null when config is null/undefined", () => {
    expect(buildFullReplacementInput(null, []).externalUrlScheme).toBeNull();
    expect(buildFullReplacementInput(undefined, []).ingressClass).toBeNull();
  });

  it("throws when persisted config carries an unrecognised enum value", () => {
    const config: Record<string, unknown> = {
      external_url_scheme: "wss",
    };
    expect(() => buildFullReplacementInput(config, [])).toThrow(
      /externalUrlScheme.*wss/,
    );
  });

  // 016/US1 (critique M1): ``updateEnvironment`` is full-replacement, so a
  // builder that dropped ``backup_ttl`` would silently clear the backup
  // retention policy every time an operator saved an env var — silent loss
  // on the feature's primary scope.
  it("preserves a persisted backup_ttl across an env-var-only save (016)", () => {
    const config: Record<string, unknown> = {
      env_vars: { LOG_LEVEL: "info" },
      backup_ttl: "2160h",
    };
    const input = buildFullReplacementInput(config, [
      { name: "LOG_LEVEL", value: "debug" },
    ]);
    expect(input.backupTtl).toBe("2160h");
    expect(input.envVars).toEqual([{ name: "LOG_LEVEL", value: "debug" }]);
  });

  it("emits null backupTtl for a non-string persisted value (016)", () => {
    expect(
      buildFullReplacementInput({ backup_ttl: 720 }, []).backupTtl,
    ).toBeNull();
  });

  // 016 (UI setter): the retention form needs to *change* backupTtl while
  // still carrying every other persisted field. The override is boxed so
  // "no override, keep persisted" stays distinguishable from "override to
  // null, clear the policy".
  describe("backupTtl override (016 UI setter)", () => {
    const config: Record<string, unknown> = {
      env_vars: { LOG_LEVEL: "info" },
      db_size: "10Gi",
      backup_ttl: "2160h",
    };

    it("keeps the persisted value when no override is passed", () => {
      expect(buildFullReplacementInput(config, []).backupTtl).toBe("2160h");
      expect(buildFullReplacementInput(config, [], {}).backupTtl).toBe("2160h");
    });

    it("applies an explicit override value", () => {
      const input = buildFullReplacementInput(config, [], {
        backupTtl: { value: "8760h" },
      });
      expect(input.backupTtl).toBe("8760h");
      // Every other field still rides through unchanged.
      expect(input.dbSize).toBe("10Gi");
    });

    it("clears the policy when the boxed override value is null", () => {
      const input = buildFullReplacementInput(config, [], {
        backupTtl: { value: null },
      });
      expect(input.backupTtl).toBeNull();
      expect(input.dbSize).toBe("10Gi");
    });

    it("can set a policy on a config that had none", () => {
      expect(
        buildFullReplacementInput({}, [], { backupTtl: { value: "720h" } })
          .backupTtl,
      ).toBe("720h");
    });
  });
});
