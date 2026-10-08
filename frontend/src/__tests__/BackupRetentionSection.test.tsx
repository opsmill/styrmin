/**
 * Backup Retention section wiring (016) — the Configuration tab's new
 * editable section, exercised through the real component with only the
 * ``updateEnvironment`` mutation stubbed. Pins the full-replacement
 * payload: editing the retention policy must not clear any other
 * persisted field.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { render, screen, userEvent, waitFor } from "@/test/utils";

import EnvironmentConfigurationTab from "@/pages/environments/EnvironmentConfigurationTab";

const updateEnvironment = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useUpdateEnvironmentMutation: () => ({
      mutateAsync: updateEnvironment,
      isPending: false,
    }),
  };
});

const ENV_ID = "00000000-0000-0000-0000-000000000001";

const NO_DEPLOYMENTS: Array<{ id: string; name: string }> = [];

/** A fully-populated config with no nested overrides (so Save is allowed). */
const FULL_CONFIG: Record<string, unknown> = {
  env_vars: { LOG_LEVEL: "info" },
  ip_whitelist: ["10.0.0.0/8"],
  fqdn_suffix: "staging.example.com",
  external_url_scheme: "https",
  external_url_port: 443,
  external_dns_endpoints_type: "NodeExternalIP",
  ingress_class: "nginx",
  db_size: "10Gi",
  backup_ttl: "2160h",
};

function retentionInput(): HTMLInputElement {
  return screen.getByTestId("backup-retention-input") as HTMLInputElement;
}

async function save(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("backup-retention-save-button"));
  await user.click(screen.getByTestId("redeploy-confirm-redeploy"));
}

describe("Backup Retention section (016)", () => {
  beforeEach(() => {
    updateEnvironment.mockReset();
    updateEnvironment.mockResolvedValue({});
  });

  it("renders the section seeded from the persisted backup_ttl", async () => {
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={FULL_CONFIG}
        deployments={NO_DEPLOYMENTS}
      />,
    );
    expect(screen.getByTestId("section-backup-retention")).toBeInTheDocument();
    expect(retentionInput().value).toBe("2160h");
  });

  it("saves a new retention value while preserving every other config field", async () => {
    const user = userEvent.setup();
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={FULL_CONFIG}
        deployments={NO_DEPLOYMENTS}
      />,
    );

    await user.clear(retentionInput());
    await user.type(retentionInput(), "8760h");
    await save(user);

    await waitFor(() => {
      expect(updateEnvironment).toHaveBeenCalledWith({
        environmentId: ENV_ID,
        input: {
          envVars: [{ name: "LOG_LEVEL", value: "info" }],
          ipWhitelist: ["10.0.0.0/8"],
          fqdnSuffix: "staging.example.com",
          externalUrlScheme: "HTTPS",
          externalUrlPort: 443,
          externalDnsEndpointsType: "NODE_EXTERNAL_IP",
          ingressClass: "nginx",
          dbSize: "10Gi",
          backupTtl: "8760h",
          dedicatedIngress: null,
          scheduling: null,
        },
      });
    });
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["GetEnvironment"],
      });
    });
    invalidate.mockRestore();
  });

  it("clears the policy to null when the input is emptied", async () => {
    const user = userEvent.setup();
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={FULL_CONFIG}
        deployments={NO_DEPLOYMENTS}
      />,
    );

    await user.clear(retentionInput());
    await save(user);

    await waitFor(() => {
      expect(updateEnvironment).toHaveBeenCalledTimes(1);
    });
    const { input } = updateEnvironment.mock.calls[0][0];
    expect(input.backupTtl).toBeNull();
    // Everything else still rides along unchanged.
    expect(input.dbSize).toBe("10Gi");
    expect(input.envVars).toEqual([{ name: "LOG_LEVEL", value: "info" }]);
  });

  it("blocks Save and never calls the mutation for an invalid duration", async () => {
    const user = userEvent.setup();
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={FULL_CONFIG}
        deployments={NO_DEPLOYMENTS}
      />,
    );

    await user.clear(retentionInput());
    await user.type(retentionInput(), "30d");
    expect(screen.getByTestId("backup-retention-error")).toHaveTextContent(
      /positive Go duration/i,
    );
    expect(screen.getByTestId("backup-retention-save-button")).toBeDisabled();
    await user.click(screen.getByTestId("backup-retention-save-button"));
    expect(updateEnvironment).not.toHaveBeenCalled();
  });

  it("shows the nested-override block and disables Save when scheduling is persisted", async () => {
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={{ ...FULL_CONFIG, scheduling: { runtime_class: "kata" } }}
        deployments={NO_DEPLOYMENTS}
      />,
    );
    expect(
      screen.getByTestId("backup-retention-blocked-warning"),
    ).toHaveTextContent(/scheduling/i);
    expect(screen.getByTestId("backup-retention-save-button")).toBeDisabled();
  });

  it("surfaces a mutation failure without losing the edited value", async () => {
    const user = userEvent.setup();
    updateEnvironment.mockRejectedValue(new Error("backend said no"));
    await render(
      <EnvironmentConfigurationTab
        environmentId={ENV_ID}
        config={FULL_CONFIG}
        deployments={NO_DEPLOYMENTS}
      />,
    );

    await user.clear(retentionInput());
    await user.type(retentionInput(), "1h30m");
    await save(user);

    await waitFor(() => {
      expect(
        screen.getByTestId("backup-retention-submit-error"),
      ).toHaveTextContent(/backend said no/i);
    });
    expect(retentionInput().value).toBe("1h30m");
  });
});
