import { describe, it, expect } from "vitest";
import { render, screen, within } from "@/test/utils";
import EnvironmentConfigurationTab from "@/pages/environments/EnvironmentConfigurationTab";

const ENV_ID = "00000000-0000-0000-0000-000000000001";

const noDeployments: Array<{ id: string; name: string; internal: boolean }> =
  [];

describe("EnvironmentConfigurationTab", () => {
  it("renders all five sections with populated values", async () => {
    const config: Record<string, unknown> = {
      env_vars: {
        OTEL_EXPORTER_OTLP_ENDPOINT: "https://otel.staging",
        LOG_LEVEL: "debug",
      },
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
    expect(screen.getByTestId("section-ip-allowlist")).toBeInTheDocument();
    expect(screen.getByTestId("section-dedicated-ingress")).toBeInTheDocument();
    expect(screen.getByTestId("section-scheduling")).toBeInTheDocument();
    expect(screen.getByTestId("section-fqdn")).toBeInTheDocument();

    // Env vars rendered.
    const envList = screen.getByTestId("env-vars-list");
    expect(
      within(envList).getByText("OTEL_EXPORTER_OTLP_ENDPOINT"),
    ).toBeInTheDocument();
    expect(
      within(envList).getByText("https://otel.staging"),
    ).toBeInTheDocument();
    expect(within(envList).getByText("LOG_LEVEL")).toBeInTheDocument();
    expect(within(envList).getByText("debug")).toBeInTheDocument();

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

    expect(
      screen.getByText("No environment variables set."),
    ).toBeInTheDocument();
    expect(screen.getByText("No IP allowlist configured.")).toBeInTheDocument();
    expect(
      screen.getByText("Using default ingress controller."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No scheduling overrides set."),
    ).toBeInTheDocument();
    expect(screen.getByText("Using cluster defaults.")).toBeInTheDocument();

    // No populated lists.
    expect(screen.queryByTestId("env-vars-list")).toBeNull();
    expect(screen.queryByTestId("ip-allowlist-list")).toBeNull();
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

    // The populated section renders its value.
    expect(screen.getByText("ONLY_ONE")).toBeInTheDocument();
    expect(screen.getByText("yes")).toBeInTheDocument();

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
    expect(
      screen.getByText("No environment variables set."),
    ).toBeInTheDocument();
  });
});
