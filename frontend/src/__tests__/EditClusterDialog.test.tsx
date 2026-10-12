/**
 * Edit the cluster config from the cluster detail page (021, User Story 3).
 *
 * `updateCluster` replaces the whole config, so the dialog must carry every
 * stored value it does not show and translate stored enum values (`http`,
 * `NodeExternalIP`, `Exists`, `NoSchedule`) to GraphQL enum names.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, userEvent } from "@/test/utils";
import type { AuthContextValue, CurrentUser } from "@/auth/AuthProvider";
import { EditClusterDialog } from "@/pages/clusters/EditClusterDialog";
import ClusterDetailPage from "@/pages/clusters/ClusterDetailPage";

const updateClusterMutateAsync = vi.fn();
const useGetClusterQuery = vi.fn();
const invalidateQueries = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useUpdateClusterMutation: () => ({
      mutateAsync: updateClusterMutateAsync,
      isPending: false,
    }),
    useGetClusterQuery: Object.assign(
      (...args: unknown[]) => useGetClusterQuery(...args),
      { getKey: actual.useGetClusterQuery.getKey },
    ),
  };
});

vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-query")>(
    "@tanstack/react-query",
  );
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries }),
  };
});

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>(
    "@tanstack/react-router",
  );
  return { ...actual, useParams: () => ({ clusterId: "cl-1" }) };
});

/** A stored config in the format the backend stores, with values the form does not show. */
const STORED_CONFIG = {
  ingress_class: "traefik",
  runtime_class: "default",
  fqdn_suffix: "old.example.com",
  external_url_scheme: "http",
  external_url_port: 8443,
  external_dns_endpoints_type: "NodeExternalIP",
  node_selector: "topology.kubernetes.io/zone=eu-west-1a",
  db_size: "20Gi",
  backup_ttl: "720h",
  dedicated_ingress: {
    implementation: "traefik",
    type: "ingress",
    service: {
      type: "NodePort",
      node_port: 30443,
      external_traffic_policy: "Local",
      ip_families: ["IPv6"],
      ip_family_policy: "SingleStack",
      annotations: { "lb.example.com/id": "abc" },
      load_balancer_ip: "10.0.0.5",
    },
  },
  standard_storage: { storage_class: "ebs-gp3" },
  fast_storage: { storage_class: "nvme-local" },
  scheduling: {
    tolerations: [
      { key: "dedicated", operator: "Exists", effect: "NoSchedule" },
      {
        key: "spot",
        operator: "Equal",
        value: "true",
        effect: "NoExecute",
        toleration_seconds: 60,
      },
    ],
    resources: {
      requests: { cpu: "100m", ephemeral_storage: "1Gi" },
    },
    runtime_class: "kata",
  },
};

/** The UpdateClusterInput for STORED_CONFIG with only the FQDN suffix changed. */
const EXPECTED_INPUT = {
  ingressClass: "traefik",
  runtimeClass: "default",
  fqdnSuffix: "new.example.com",
  externalUrlScheme: "HTTP",
  externalUrlPort: 8443,
  externalDnsEndpointsType: "NODE_EXTERNAL_IP",
  nodeSelector: "topology.kubernetes.io/zone=eu-west-1a",
  dbSize: "20Gi",
  backupTtl: "720h",
  dedicatedIngress: {
    implementation: "traefik",
    type: "ingress",
    service: {
      type: "NodePort",
      nodePort: 30443,
      externalTrafficPolicy: "Local",
      ipFamilies: ["IPv6"],
      ipFamilyPolicy: "SingleStack",
      annotations: { "lb.example.com/id": "abc" },
      loadBalancerIp: "10.0.0.5",
    },
  },
  standardStorage: { storageClass: "ebs-gp3" },
  fastStorage: { storageClass: "nvme-local" },
  scheduling: {
    tolerations: [
      { key: "dedicated", operator: "EXISTS", effect: "NO_SCHEDULE" },
      {
        key: "spot",
        operator: "EQUAL",
        value: "true",
        effect: "NO_EXECUTE",
        tolerationSeconds: 60,
      },
    ],
    resources: {
      requests: { cpu: "100m", ephemeralStorage: "1Gi" },
    },
    runtimeClass: "kata",
  },
};

const CLUSTER = { id: "cl-1", name: "default", config: STORED_CONFIG };

type Role = "READ_ONLY" | "READ_WRITE" | "ADMIN";

function authFor(role: Role, effectiveRole: Role = role): AuthContextValue {
  const user: CurrentUser = {
    id: `user-${role}`,
    username: `${role.toLowerCase()}-user`,
    displayName: `${role} User`,
    role,
    effectiveRole,
    active: true,
  };
  return {
    currentUser: user,
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

async function openDialog(
  cluster: {
    id: string;
    name: string;
    config: Record<string, unknown>;
  } = CLUSTER,
) {
  const user = userEvent.setup();
  await render(<EditClusterDialog cluster={cluster} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  return user;
}

async function replaceFqdnSuffix(
  user: ReturnType<typeof userEvent.setup>,
  value: string,
) {
  const input = screen.getByLabelText("FQDN Suffix");
  await user.clear(input);
  await user.type(input, value);
}

/** The `input` variable of the last `updateCluster` call. */
function submittedInput(): Record<string, unknown> {
  const [variables] = updateClusterMutateAsync.mock.calls.at(-1)!;
  return (variables as { input: Record<string, unknown> }).input;
}

/** Every object key in `value`, except keys inside the JSON-typed `annotations` map. */
function allKeys(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(allKeys);
  if (value === null || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, nested]) =>
    key === "annotations" ? [key] : [key, ...allKeys(nested)],
  );
}

describe("EditClusterDialog", () => {
  beforeEach(() => {
    updateClusterMutateAsync.mockReset();
    updateClusterMutateAsync.mockResolvedValue({
      updateCluster: { ...CLUSTER, capabilities: {} },
    });
    invalidateQueries.mockReset();
  });

  it("prefills the form from the stored cluster config", async () => {
    await openDialog();

    expect(screen.getByLabelText("Ingress Class")).toHaveValue("traefik");
    expect(screen.getByLabelText("FQDN Suffix")).toHaveValue("old.example.com");
    expect(screen.getByLabelText("Runtime Class")).toHaveValue("default");
    expect(screen.getByLabelText("External URL Scheme")).toHaveValue("http");
    expect(screen.getByLabelText("External URL Port")).toHaveValue(8443);
    expect(screen.getByLabelText("external-dns Endpoints Type")).toHaveValue(
      "NodeExternalIP",
    );
    expect(
      screen.getByRole("checkbox", { name: "Dedicated Ingress" }),
    ).toBeChecked();
    expect(screen.getByLabelText("Implementation")).toHaveValue("traefik");
    expect(screen.getByLabelText("Type")).toHaveValue("ingress");
    expect(screen.getByLabelText("Service Type")).toHaveValue("NodePort");
    expect(screen.getByLabelText("NodePort")).toHaveValue(30443);
    expect(screen.getByLabelText("External Traffic Policy")).toHaveValue(
      "Local",
    );
    expect(screen.getByRole("checkbox", { name: "IPv4" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "IPv6" })).toBeChecked();
    expect(screen.getByLabelText("IP Family Policy")).toHaveValue(
      "SingleStack",
    );
    expect(
      screen.getByRole("checkbox", { name: "Standard Storage" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Fast Storage" }),
    ).toBeChecked();
    const storageClasses = screen.getAllByLabelText("Storage Class");
    expect(storageClasses.map((el) => (el as HTMLInputElement).value)).toEqual([
      "ebs-gp3",
      "nvme-local",
    ]);
  });

  it("changing only the FQDN suffix keeps every other stored value", async () => {
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateClusterMutateAsync).toHaveBeenCalled());
    expect(updateClusterMutateAsync).toHaveBeenCalledWith({
      clusterId: "cl-1",
      input: EXPECTED_INPUT,
    });
    expect(allKeys(submittedInput()).filter((k) => k.includes("_"))).toEqual(
      [],
    );
  });

  it("keeps a dedicated ingress stored as an empty object turned on", async () => {
    const user = await openDialog({
      id: "cl-1",
      name: "default",
      config: {
        ingress_class: "traefik",
        runtime_class: "default",
        dedicated_ingress: {},
      },
    });

    await replaceFqdnSuffix(user, "new.example.com");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateClusterMutateAsync).toHaveBeenCalled());
    expect(submittedInput()).toEqual({
      ingressClass: "traefik",
      runtimeClass: "default",
      fqdnSuffix: "new.example.com",
      dedicatedIngress: {},
    });
  });

  it("removes a value the administrator clears in the form", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("checkbox", { name: "Fast Storage" }));
    await user.click(
      screen.getByRole("checkbox", { name: "Dedicated Ingress" }),
    );
    await user.clear(screen.getByLabelText("FQDN Suffix"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateClusterMutateAsync).toHaveBeenCalled());
    const input = submittedInput();
    expect(input).not.toHaveProperty("fastStorage");
    expect(input).not.toHaveProperty("dedicatedIngress");
    expect(input).not.toHaveProperty("fqdnSuffix");
    expect(input).toMatchObject({
      standardStorage: { storageClass: "ebs-gp3" },
      scheduling: EXPECTED_INPUT.scheduling,
    });
  });

  it("blocks submission and shows the reason when a value is invalid", async () => {
    const user = await openDialog();

    const [standardClass, fastClass] =
      screen.getAllByLabelText("Storage Class");
    await user.clear(standardClass!);
    await user.clear(fastClass!);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(
        "Storage class is required when standard storage is enabled",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Storage class is required when fast storage is enabled",
      ),
    ).toBeInTheDocument();
    expect(updateClusterMutateAsync).not.toHaveBeenCalled();
  });

  it("shows the mutation error and keeps the dialog open", async () => {
    updateClusterMutateAsync.mockRejectedValue(
      new Error("An environment of this cluster is being cloned"),
    );
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("An environment of this cluster is being cloned"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("FQDN Suffix")).toHaveValue("new.example.com");
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("refreshes the cluster and closes after a successful save", async () => {
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(screen.queryByLabelText("FQDN Suffix")).not.toBeInTheDocument(),
    );
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["GetCluster", { clusterId: "cl-1" }],
    });
  });
});

describe("ClusterDetailPage edit button", () => {
  beforeEach(() => {
    useGetClusterQuery.mockReturnValue({
      data: {
        cluster: {
          ...CLUSTER,
          capabilities: {},
          createdOn: "2026-10-01T00:00:00Z",
          updatedOn: null,
          environments: [],
        },
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    });
  });

  it("shows the Edit button to a user whose effective role is ADMIN", async () => {
    await render(<ClusterDetailPage />, {
      auth: authFor("READ_ONLY", "ADMIN"),
    });

    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it.each<Role>(["READ_ONLY", "READ_WRITE"])(
    "hides the Edit button from a user whose effective role is %s",
    async (role) => {
      await render(<ClusterDetailPage />, { auth: authFor("ADMIN", role) });

      expect(screen.getByText("Configuration")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Edit" }),
      ).not.toBeInTheDocument();
    },
  );
});
