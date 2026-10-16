/**
 * Edit the cluster config from the cluster detail page (021, User Story 3).
 *
 * `updateCluster` replaces the whole config, so the dialog must carry every
 * stored value it does not show and translate stored enum values (`http`,
 * `NodeExternalIP`, `Exists`, `NoSchedule`) to GraphQL enum names. Saving is
 * reviewed first with a dry run, then the result of the save is shown.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, within, userEvent } from "@/test/utils";
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
  const input = screen.getByLabelText("FQDN suffix");
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

type Outcome = {
  cluster: { config: Record<string, unknown> } & Record<string, unknown>;
  dryRun: boolean;
  redeployed: unknown[];
  waitingForIngress: unknown[];
  skippedRestoring: unknown[];
  failedToStart: unknown[];
  unchangedCount: number;
  ingressControllers: unknown[];
  failedEnvironments: unknown[];
};

function deployment(name: string, environment: string, taskId?: string) {
  return {
    deploymentId: `dep-${name}`,
    deploymentName: name,
    environmentId: `env-${environment}`,
    environmentName: environment,
    taskId: taskId ?? null,
  };
}

function outcome(overrides: Partial<Outcome> = {}): Outcome {
  return {
    cluster: {
      ...CLUSTER,
      capabilities: {},
      createdOn: "2026-10-01T00:00:00Z",
      updatedOn: null,
    },
    dryRun: true,
    redeployed: [deployment("web", "staging")],
    waitingForIngress: [],
    skippedRestoring: [],
    failedToStart: [],
    unchangedCount: 2,
    ingressControllers: [],
    failedEnvironments: [],
    ...overrides,
  };
}

/** Answer the dry run with `plan` and the save with `result`. */
function respond(plan: Outcome = outcome(), result?: Outcome) {
  updateClusterMutateAsync.mockImplementation(
    async ({ dryRun }: { dryRun: boolean }) => ({
      updateCluster: dryRun
        ? plan
        : (result ?? {
            ...plan,
            dryRun: false,
            redeployed: [deployment("web", "staging", "task-1")],
          }),
    }),
  );
}

async function review(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Review changes" }));
  return screen.findByTestId("cluster-update-review");
}

async function reviewAndSave(user: ReturnType<typeof userEvent.setup>) {
  await review(user);
  await user.click(screen.getByRole("button", { name: "Save and redeploy" }));
  return screen.findByTestId("cluster-update-result");
}

describe("EditClusterDialog", () => {
  beforeEach(() => {
    updateClusterMutateAsync.mockReset();
    respond();
    invalidateQueries.mockReset();
  });

  it("prefills the form from the stored cluster config", async () => {
    await openDialog();

    expect(screen.getByLabelText("Ingress class")).toHaveValue("traefik");
    expect(screen.getByLabelText("FQDN suffix")).toHaveValue("old.example.com");
    expect(screen.getByLabelText("Runtime class")).toHaveValue("default");
    expect(screen.getByLabelText("External URL scheme")).toHaveValue("http");
    expect(screen.getByLabelText("External URL port")).toHaveValue(8443);
    expect(screen.getByLabelText("External DNS endpoints type")).toHaveValue(
      "NodeExternalIP",
    );
    expect(
      screen.getByRole("checkbox", { name: "Dedicated ingress" }),
    ).toBeChecked();
    expect(screen.getByLabelText("Implementation")).toHaveValue("traefik");
    expect(screen.getByLabelText("Routing type")).toHaveValue("ingress");
    expect(screen.getByLabelText("Service type")).toHaveValue("NodePort");
    expect(screen.getByLabelText("NodePort")).toHaveValue(30443);
    expect(screen.getByLabelText("External traffic policy")).toHaveValue(
      "Local",
    );
    expect(screen.getByRole("checkbox", { name: "IPv4" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "IPv6" })).toBeChecked();
    expect(screen.getByLabelText("IP family policy")).toHaveValue(
      "SingleStack",
    );
    expect(
      screen.getByRole("checkbox", { name: "Standard storage" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Fast storage" }),
    ).toBeChecked();
    expect(screen.getByLabelText("Standard storage class")).toHaveValue(
      "ebs-gp3",
    );
    expect(screen.getByLabelText("Fast storage class")).toHaveValue(
      "nvme-local",
    );
  });

  it("names the stored values the form keeps without listing them", async () => {
    await openDialog();

    expect(
      screen.getByText(
        /Scheduling, the database size and the backup retention are kept as they are/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/node selector/i)).not.toBeInTheDocument();
  });

  it("changing only the FQDN suffix keeps every other stored value", async () => {
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await reviewAndSave(user);

    expect(updateClusterMutateAsync.mock.calls).toEqual([
      [{ clusterId: "cl-1", input: EXPECTED_INPUT, dryRun: true }],
      [{ clusterId: "cl-1", input: EXPECTED_INPUT, dryRun: false }],
    ]);
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
    await review(user);

    expect(submittedInput()).toEqual({
      ingressClass: "traefik",
      runtimeClass: "default",
      fqdnSuffix: "new.example.com",
      dedicatedIngress: {},
    });
  });

  it("keeps stored values the form does not list", async () => {
    const config = {
      ingress_class: "traefik",
      runtime_class: "default",
      dedicated_ingress: {
        type: "gateway-api",
        service: { type: "ExternalName", external_traffic_policy: "Hybrid" },
      },
    };
    const user = await openDialog({ id: "cl-1", name: "default", config });

    expect(screen.getByLabelText("Routing type")).toHaveValue("gateway-api");
    expect(screen.getByLabelText("Service type")).toHaveValue("ExternalName");
    await review(user);

    expect(submittedInput()).toEqual({
      ingressClass: "traefik",
      runtimeClass: "default",
      dedicatedIngress: {
        type: "gateway-api",
        service: { type: "ExternalName", externalTrafficPolicy: "Hybrid" },
      },
    });
  });

  it("saves a scheduling value that refers to another deployment", async () => {
    const user = await openDialog({
      id: "cl-1",
      name: "default",
      config: {
        ingress_class: "traefik",
        runtime_class: "default",
        scheduling: {
          pod_affinity: {
            required: [
              {
                topology_key: "kubernetes.io/hostname",
                deployment_ref: { deployment_name: "db" },
              },
            ],
          },
        },
      },
    });

    await review(user);

    expect(submittedInput()).toMatchObject({
      scheduling: {
        podAffinity: {
          required: [
            {
              topologyKey: "kubernetes.io/hostname",
              deploymentRef: { deploymentName: "db" },
            },
          ],
        },
      },
    });
  });

  it("removes a value the administrator clears in the form", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("checkbox", { name: "Fast storage" }));
    await user.click(
      screen.getByRole("checkbox", { name: "Dedicated ingress" }),
    );
    await user.clear(screen.getByLabelText("FQDN suffix"));
    await review(user);

    const input = submittedInput();
    expect(input).not.toHaveProperty("fastStorage");
    expect(input).not.toHaveProperty("dedicatedIngress");
    expect(input).not.toHaveProperty("fqdnSuffix");
    expect(input).toMatchObject({
      standardStorage: { storageClass: "ebs-gp3" },
      scheduling: EXPECTED_INPUT.scheduling,
    });
  });

  it("blocks submission, shows the reason and focuses the first invalid field", async () => {
    const user = await openDialog();

    await user.clear(screen.getByLabelText("Standard storage class"));
    await user.clear(screen.getByLabelText("Fast storage class"));
    await user.click(screen.getByRole("button", { name: "Review changes" }));

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
    const standard = screen.getByLabelText("Standard storage class");
    expect(standard).toHaveAttribute("aria-invalid", "true");
    expect(standard).toHaveAccessibleDescription(
      "Storage class is required when standard storage is enabled",
    );
    await waitFor(() => expect(standard).toHaveFocus());
    expect(updateClusterMutateAsync).not.toHaveBeenCalled();
  });

  it("states the defaults of the empty values", async () => {
    await openDialog();

    expect(screen.getByLabelText("Ingress class")).toHaveAccessibleDescription(
      "Leave empty to use traefik.",
    );
    expect(screen.getByLabelText("Runtime class")).toHaveAccessibleDescription(
      "Leave empty to use default.",
    );
    expect(
      within(screen.getByLabelText("External URL scheme")).getByRole("option", {
        name: "Default (https)",
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Service type")).getByRole("option", {
        name: "Default (LoadBalancer)",
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Routing type")).getByRole("option", {
        name: "Default (ingress)",
      }),
    ).toBeInTheDocument();
  });

  it("reviews the changed values and the deployments before saving", async () => {
    respond(
      outcome({
        redeployed: [
          deployment("web", "staging"),
          deployment("api", "staging"),
          deployment("shop", "production"),
        ],
        waitingForIngress: [deployment("blog", "preview")],
        skippedRestoring: [deployment("db", "production")],
      }),
    );
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    const reviewStep = await review(user);

    expect(updateClusterMutateAsync).toHaveBeenCalledTimes(1);
    const changes = within(reviewStep).getByRole("region", {
      name: "Changed values",
    });
    expect(within(changes).getByText("FQDN suffix")).toBeInTheDocument();
    expect(within(changes).getByText("old.example.com")).toBeInTheDocument();
    expect(within(changes).getByText("new.example.com")).toBeInTheDocument();
    expect(within(changes).getAllByRole("row")).toHaveLength(2);
    const redeploys = within(reviewStep).getByRole("region", {
      name: "Deployments to redeploy (3)",
    });
    expect(redeploys).toHaveTextContent("staging: web, api");
    expect(redeploys).toHaveTextContent("production: shop");
    expect(
      within(reviewStep).getByRole("region", {
        name: "Waiting for the dedicated ingress controller (1)",
      }),
    ).toHaveTextContent("preview: blog");
    expect(
      within(reviewStep).getByRole("region", {
        name: "Not redeployed while a restore runs (1)",
      }),
    ).toHaveTextContent("production: db");
    expect(screen.getByText("Application URLs change")).toBeInTheDocument();
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("goes back to the form with the edited values", async () => {
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await review(user);
    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByLabelText("FQDN suffix")).toHaveValue("new.example.com");
  });

  it("warns about storage class and dedicated ingress changes", async () => {
    respond(
      outcome({
        ingressControllers: [
          {
            environmentId: "env-staging",
            environmentName: "staging",
            action: "REMOVE",
            failed: false,
          },
        ],
      }),
    );
    const user = await openDialog();

    await user.clear(screen.getByLabelText("Standard storage class"));
    await user.type(screen.getByLabelText("Standard storage class"), "premium");
    await user.click(
      screen.getByRole("checkbox", { name: "Dedicated ingress" }),
    );
    await review(user);

    expect(
      screen.getByText("Storage class change can fail deployments"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/saving again does not retry them/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /The dedicated ingress controller of staging is removed once its applications are redeployed without it\. The service annotations and the load balancer IP are not kept\./,
      ),
    ).toBeInTheDocument();
  });

  it("names the environments that get a dedicated ingress controller", async () => {
    respond(
      outcome({
        ingressControllers: [
          {
            environmentId: "env-staging",
            environmentName: "staging",
            action: "CREATE",
            failed: false,
          },
        ],
      }),
    );
    const user = await openDialog({
      id: "cl-1",
      name: "default",
      config: { ingress_class: "traefik", runtime_class: "default" },
    });

    await user.click(
      screen.getByRole("checkbox", { name: "Dedicated ingress" }),
    );
    await review(user);

    expect(
      screen.getByText(
        /A dedicated ingress controller is created in staging\. With the service type LoadBalancer, each controller can create a load balancer in your cloud provider\./,
      ),
    ).toBeInTheDocument();
  });

  it("says there is nothing to save when nothing changed and nothing is redeployed", async () => {
    respond(outcome({ redeployed: [] }));
    const user = await openDialog();

    await review(user);

    expect(screen.getByText(/There is nothing to save\./)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save and redeploy" }),
    ).toBeDisabled();
  });

  it("explains why saving an unchanged configuration again is useful", async () => {
    const user = await openDialog();

    await review(user);

    expect(
      screen.getByText(/No value changed\. Saving again redeploys/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save and redeploy" }),
    ).toBeEnabled();
  });

  it("warns when another administrator changed the configuration", async () => {
    respond(
      outcome({
        cluster: {
          ...CLUSTER,
          config: { ...STORED_CONFIG, db_size: "50Gi" },
        },
      }),
    );
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    const reviewStep = await review(user);

    expect(
      screen.getByText(
        "The configuration changed after you opened this dialog",
      ),
    ).toBeInTheDocument();
    const changes = within(reviewStep).getByRole("region", {
      name: "Changed values",
    });
    expect(within(changes).getByText("Database size")).toBeInTheDocument();
    expect(within(changes).getByText("50Gi")).toBeInTheDocument();
  });

  it("shows the mutation error next to the buttons and keeps the dialog open", async () => {
    updateClusterMutateAsync.mockRejectedValue(
      new Error(
        "Nothing was saved: environment 'staging' is part of an environment clone that is still running. Save again when the clone has finished.",
      ),
    );
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await user.click(screen.getByRole("button", { name: "Review changes" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/environment 'staging' is part of an/);
    expect(alert.parentElement).toContainElement(
      screen.getByRole("button", { name: "Review changes" }),
    );
    expect(screen.getByLabelText("FQDN suffix")).toHaveValue("new.example.com");
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("shows what the save started, refreshes the cluster and closes on Done", async () => {
    respond(
      outcome(),
      outcome({
        dryRun: false,
        redeployed: [
          deployment("web", "staging", "task-1"),
          deployment("api", "staging", "task-2"),
        ],
        waitingForIngress: [deployment("blog", "preview")],
      }),
    );
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    const result = await reviewAndSave(user);

    expect(result).toHaveTextContent(
      "The configuration was saved. 2 deployments are being redeployed.",
    );
    expect(within(result).getByRole("link", { name: "web" })).toHaveAttribute(
      "href",
      "/environments/env-staging/deployments/dep-web",
    );
    expect(
      within(result).getByRole("region", {
        name: "Waiting for the dedicated ingress controller (1)",
      }),
    ).toHaveTextContent("preview: blog");
    expect(screen.queryByText("Save again to retry them.")).toBeNull();
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["GetCluster", { clusterId: "cl-1" }],
    });

    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(
        screen.queryByTestId("cluster-update-result"),
      ).not.toBeInTheDocument(),
    );
  });

  it("asks to save again when some redeploys did not start", async () => {
    respond(
      outcome(),
      outcome({
        dryRun: false,
        redeployed: [deployment("web", "staging", "task-1")],
        failedToStart: [deployment("api", "staging")],
        failedEnvironments: [
          { environmentId: "env-broken", environmentName: "broken" },
        ],
      }),
    );
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    const result = await reviewAndSave(user);

    expect(screen.getByText("Save again to retry them.")).toBeInTheDocument();
    expect(
      within(result).getByRole("region", { name: "Could not start (1)" }),
    ).toHaveTextContent("staging: api");
    expect(result).toHaveTextContent(
      "These environments could not be evaluated: broken.",
    );
  });

  it("does not close while a request runs", async () => {
    let finish: (value: unknown) => void = () => {};
    updateClusterMutateAsync.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await user.click(screen.getByRole("button", { name: "Review changes" }));

    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByLabelText("FQDN suffix")).toBeInTheDocument();

    finish({ updateCluster: outcome() });
    expect(
      await screen.findByTestId("cluster-update-review"),
    ).toBeInTheDocument();
  });

  it("asks before Escape or Cancel discards edited values", async () => {
    const user = await openDialog();

    await replaceFqdnSuffix(user, "new.example.com");
    await user.keyboard("{Escape}");

    expect(
      screen.getByRole("alertdialog", { name: "Discard your changes?" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByLabelText("FQDN suffix")).toHaveValue("new.example.com");

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() =>
      expect(screen.queryByLabelText("FQDN suffix")).not.toBeInTheDocument(),
    );
    expect(updateClusterMutateAsync).not.toHaveBeenCalled();
  });

  it("closes at once when nothing was edited", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByLabelText("FQDN suffix")).not.toBeInTheDocument(),
    );
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
