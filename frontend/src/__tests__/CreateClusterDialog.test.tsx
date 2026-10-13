/**
 * CreateClusterDialog submission (021-cluster-config-update).
 *
 * The config fields moved into the shared ClusterConfigFields component; these
 * tests pin the config the create dialog sends so the move cannot change it.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, userEvent } from "@/test/utils";
import { CreateClusterDialog } from "@/pages/settings/CreateClusterDialog";

const createClusterMutateAsync = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useCreateClusterMutation: () => ({
      mutateAsync: createClusterMutateAsync,
      isPending: false,
    }),
  };
});

async function openDialog() {
  const user = userEvent.setup();
  await render(<CreateClusterDialog onCreated={() => {}} />);
  await user.click(screen.getByRole("button", { name: /New Cluster/i }));
  return user;
}

describe("CreateClusterDialog", () => {
  beforeEach(() => {
    createClusterMutateAsync.mockReset();
    createClusterMutateAsync.mockResolvedValue({
      createCluster: { id: "cl-1", name: "default", config: {} },
    });
  });

  it("sends a null config when no advanced value is set", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: /^Create$/ }));

    await waitFor(() => expect(createClusterMutateAsync).toHaveBeenCalled());
    expect(createClusterMutateAsync).toHaveBeenCalledWith({
      name: "default",
      config: null,
    });
  });

  it("sends every advanced value in the stored config format", async () => {
    const user = await openDialog();

    await user.click(
      screen.getByRole("button", { name: /Advanced Configuration/i }),
    );
    await user.type(screen.getByLabelText("Ingress class"), "nginx");
    await user.type(screen.getByLabelText("FQDN suffix"), "example.com");
    await user.selectOptions(
      screen.getByLabelText("External URL scheme"),
      "https",
    );
    await user.type(screen.getByLabelText("External URL port"), "8443");
    await user.selectOptions(
      screen.getByLabelText("External DNS endpoints type"),
      "NodeExternalIP",
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Dedicated ingress" }),
    );
    await user.type(screen.getByLabelText("Implementation"), "traefik");
    await user.selectOptions(screen.getByLabelText("Service type"), "NodePort");
    await user.type(screen.getByLabelText("NodePort"), "30443");
    await user.click(screen.getByRole("checkbox", { name: "IPv6" }));
    await user.selectOptions(
      screen.getByLabelText("IP family policy"),
      "SingleStack",
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Standard storage" }),
    );
    await user.type(screen.getByLabelText("Standard storage class"), "ebs-gp3");
    await user.click(screen.getByRole("button", { name: /^Create$/ }));

    await waitFor(() => expect(createClusterMutateAsync).toHaveBeenCalled());
    expect(createClusterMutateAsync).toHaveBeenCalledWith({
      name: "default",
      config: {
        ingress_class: "nginx",
        fqdn_suffix: "example.com",
        external_url_scheme: "https",
        external_url_port: 8443,
        external_dns_endpoints_type: "NodeExternalIP",
        dedicated_ingress: {
          implementation: "traefik",
          service: {
            type: "NodePort",
            node_port: 30443,
            ip_family_policy: "SingleStack",
            ip_families: ["IPv6"],
          },
        },
        standard_storage: { storage_class: "ebs-gp3" },
      },
    });
  });

  it("blocks submission when standard storage has no storage class", async () => {
    const user = await openDialog();

    await user.click(
      screen.getByRole("button", { name: /Advanced Configuration/i }),
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Standard storage" }),
    );
    await user.click(screen.getByRole("button", { name: /^Create$/ }));

    expect(
      await screen.findByText(
        "Storage class is required when standard storage is enabled",
      ),
    ).toBeInTheDocument();
    expect(createClusterMutateAsync).not.toHaveBeenCalled();
    const storageClass = screen.getByLabelText("Standard storage class");
    expect(storageClass).toHaveAttribute("aria-invalid", "true");
    expect(storageClass).toHaveAccessibleDescription(
      "Storage class is required when standard storage is enabled",
    );
    expect(storageClass).toHaveFocus();
  });

  it("states the value used when Ingress class or Runtime class is empty", async () => {
    const user = await openDialog();

    await user.click(
      screen.getByRole("button", { name: /Advanced Configuration/i }),
    );

    expect(screen.getByLabelText("Ingress class")).toHaveAccessibleDescription(
      "Leave empty to use traefik.",
    );
    expect(screen.getByLabelText("Runtime class")).toHaveAccessibleDescription(
      "Leave empty to use default.",
    );
    expect(
      screen.getByRole("option", { name: "Default (https)" }),
    ).toBeInTheDocument();
  });
});
