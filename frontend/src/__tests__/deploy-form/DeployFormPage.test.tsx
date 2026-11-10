/**
 * DeployFormPage driver-version dropdown tests (feature 013 follow-up).
 *
 * Asserts the trigger and items each render
 * `<driverName> v<version>@<short>` for fixture drivers with content
 * hashes, and that two driver versions with the same `version` string
 * but different fingerprints render as visually distinct options.
 * Also covers the "Component replicas" section (023).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRouter,
  createRootRoute,
  createRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

import {
  AuthContext,
  type AuthContextValue,
  type CurrentUser,
} from "@/auth/AuthProvider";
import { ThemeProvider } from "@/hooks/use-theme";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import DeployFormPage from "@/pages/deployments/DeployFormPage";
import type { ListApplicationDriversQuery } from "@/generated/graphql";

const useListApplicationDriversQueryMock = vi.fn();
const noopMutationResult = {
  mutateAsync: vi.fn().mockResolvedValue({}),
  mutate: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
};
vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListApplicationDriversQuery: (...args: unknown[]) =>
      useListApplicationDriversQueryMock(...args),
    useDeployMutation: () => noopMutationResult,
  };
});

function makeUser(): CurrentUser {
  return {
    id: "user-rw",
    username: "rw-user",
    displayName: "RW User",
    role: "READ_WRITE",
    effectiveRole: "READ_WRITE",
    active: true,
  };
}

function makeAuthValue(): AuthContextValue {
  return {
    currentUser: makeUser(),
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

type DriversShape = ListApplicationDriversQuery["applicationDrivers"];

function makeQueryResult(drivers: DriversShape) {
  return {
    data: { applicationDrivers: drivers } as ListApplicationDriversQuery,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  };
}

function makeTestRouter() {
  const rootRoute = createRootRoute();
  const homeRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>home</div>,
  });
  const envRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId",
    component: () => <div>environment</div>,
  });
  const deployRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId/deploy",
    component: () => <DeployFormPage />,
  });
  return createRouter({
    routeTree: rootRoute.addChildren([homeRoute, envRoute, deployRoute]),
    history: createMemoryHistory({
      initialEntries: ["/environments/env-1/deploy"],
    }),
  });
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

async function renderPage() {
  const router = makeTestRouter();
  await router.load();
  const qc = makeQueryClient();
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={makeAuthValue()}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
}

describe("DeployFormPage driver-version dropdown", () => {
  beforeEach(() => {
    useListApplicationDriversQueryMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders each dropdown option as <driverName> v<version>@<short>", async () => {
    const drivers: DriversShape = [
      {
        id: "drv-nginx",
        name: "nginx",
        versions: [
          {
            id: "v-nginx-1",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            createdOn: "2026-10-01T00:00:00Z",
            contentHash: "a".repeat(64),
            sourceCommitSha: null,
            parameters: [],
            componentConfigs: [],
            services: [],
          },
        ],
      },
      {
        id: "drv-redis",
        name: "redis",
        versions: [
          {
            id: "v-redis-1",
            version: "2.0.0",
            supportedVersions: "*",
            defaultVersion: null,
            createdOn: "2026-10-01T00:00:00Z",
            contentHash: null,
            sourceCommitSha: "b".repeat(40),
            parameters: [],
            componentConfigs: [],
            services: [],
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );

    await renderPage();

    const user = userEvent.setup();
    const trigger = await screen.findByTestId("driver-version-select");
    await user.click(trigger);

    // Each option renders `<driverName> v<version>@<short>`.
    await waitFor(() => {
      expect(screen.getByText("nginx v1.2.3@aaaaaaa")).toBeInTheDocument();
    });
    expect(screen.getByText("redis v2.0.0@bbbbbbb")).toBeInTheDocument();
  });

  it("shows the same formatted label on the trigger when a version is selected", async () => {
    const drivers: DriversShape = [
      {
        id: "drv-nginx",
        name: "nginx",
        versions: [
          {
            id: "v-nginx-1",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            createdOn: "2026-10-01T00:00:00Z",
            contentHash: "a".repeat(64),
            sourceCommitSha: null,
            parameters: [],
            componentConfigs: [],
            services: [],
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );

    await renderPage();

    const user = userEvent.setup();
    const trigger = await screen.findByTestId("driver-version-select");
    await user.click(trigger);

    const option = await screen.findByText("nginx v1.2.3@aaaaaaa");
    await user.click(option);

    await waitFor(() => {
      const trigger2 = screen.getByTestId("driver-version-select");
      expect(
        within(trigger2).getByText("nginx v1.2.3@aaaaaaa"),
      ).toBeInTheDocument();
    });
  });

  it("renders two same-version different-fingerprint driver versions as visually distinct options", async () => {
    const drivers: DriversShape = [
      {
        id: "drv-nginx",
        name: "nginx",
        versions: [
          {
            id: "v-nginx-old",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            createdOn: "2026-10-01T00:00:00Z",
            contentHash: "a".repeat(64),
            sourceCommitSha: null,
            parameters: [],
            componentConfigs: [],
            services: [],
          },
          {
            id: "v-nginx-new",
            version: "1.2.3",
            supportedVersions: "*",
            defaultVersion: null,
            createdOn: "2026-10-01T00:00:00Z",
            contentHash: "c".repeat(64),
            sourceCommitSha: null,
            parameters: [],
            componentConfigs: [],
            services: [],
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );

    await renderPage();

    const user = userEvent.setup();
    const trigger = await screen.findByTestId("driver-version-select");
    await user.click(trigger);

    await waitFor(() => {
      expect(screen.getByText("nginx v1.2.3@aaaaaaa")).toBeInTheDocument();
    });
    expect(screen.getByText("nginx v1.2.3@ccccccc")).toBeInTheDocument();
  });
});

describe("DeployFormPage component replicas (023)", () => {
  const BELOW_ONE = "Must be 1 or more. To run no pods, stop the component.";
  const drivers: DriversShape = [
    {
      id: "drv-simple",
      name: "simple-app",
      versions: [
        {
          id: "v-simple-4",
          version: "4",
          supportedVersions: "*",
          defaultVersion: "1.0.0",
          createdOn: "2026-10-01T00:00:00Z",
          contentHash: "d".repeat(64),
          sourceCommitSha: null,
          parameters: [],
          componentConfigs: [
            { name: "server", replicas: 2, singleton: false },
            { name: "worker", replicas: null, singleton: false },
            { name: "database", replicas: null, singleton: true },
          ],
          services: [],
        },
      ],
    },
  ] as DriversShape;

  beforeEach(() => {
    useListApplicationDriversQueryMock.mockReset();
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );
    noopMutationResult.mutateAsync.mockClear();
  });

  async function selectVersion(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByTestId("driver-version-select"));
    // The select popup can keep `pointer-events: none` while it opens.
    await userEvent
      .setup({ pointerEventsCheck: 0 })
      .click(await screen.findByText("simple-app v4@ddddddd"));
    await screen.findByRole("group", { name: "Component replicas" });
  }

  it("lists no section until a driver version is selected", async () => {
    await renderPage();

    await screen.findByTestId("driver-version-select");
    expect(
      screen.queryByRole("group", { name: "Component replicas" }),
    ).toBeNull();
  });

  it("lists the selected version's components with the replicas field", async () => {
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    const section = screen.getByRole("group", { name: "Component replicas" });
    const server = within(section).getByRole("spinbutton", {
      name: "Replicas for server",
    });
    expect(server).toBe(screen.getByTestId("comp-replicas-server"));
    expect(server).toHaveAttribute("placeholder", "2 (driver default)");
    expect(
      within(section).getByRole("spinbutton", { name: "Replicas for worker" }),
    ).toHaveAttribute("placeholder", "set by the chart");
    const database = within(section).getByRole("textbox", {
      name: "Replicas for database",
    });
    expect(database).toHaveValue("1 (singleton)");
    expect(database).toHaveAttribute("readonly");
  });

  it("sends config.components only for components with a value", async () => {
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    await user.type(screen.getByLabelText("Deployment Name"), "my-app");
    await user.type(screen.getByTestId("comp-replicas-server"), "3");
    await user.click(screen.getByRole("button", { name: "Deploy" }));

    await waitFor(() =>
      expect(noopMutationResult.mutateAsync).toHaveBeenCalledTimes(1),
    );
    expect(noopMutationResult.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        driver: "simple-app",
        name: "my-app",
        config: { components: [{ name: "server", replicas: 3 }] },
        // The selected driver version is pinned, so the server checks the
        // values against the version whose fields the form shows.
        driverVersionId: "v-simple-4",
      }),
    );
  });

  it("labels each field with its component name", async () => {
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    const section = screen.getByRole("group", { name: "Component replicas" });
    for (const name of ["server", "worker", "database"]) {
      expect(within(section).getByText(name, { selector: "label" })).toBe(
        section.querySelector(`label[for="comp-${name}-replicas"]`),
      );
    }
  });

  it("disables Deploy and names the component while a count is invalid", async () => {
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    await user.type(screen.getByTestId("comp-replicas-worker"), "0");

    const deploy = screen.getByRole("button", { name: "Deploy" });
    expect(deploy).toBeDisabled();
    expect(screen.getByTestId("deploy-blocked-reason")).toHaveTextContent(
      "Fix the replica count of worker before deploying.",
    );
    expect(deploy).toHaveAttribute("aria-describedby", "deploy-blocked-reason");
    expect(screen.queryByText("Deployment failed")).toBeNull();

    await user.clear(screen.getByTestId("comp-replicas-worker"));
    expect(deploy).toBeEnabled();
    expect(screen.queryByTestId("deploy-blocked-reason")).toBeNull();
  });

  it("names a driver parameter that sets the same count", async () => {
    const withParameter: DriversShape = [
      {
        ...drivers[0],
        versions: [
          {
            ...drivers[0].versions[0],
            parameters: [
              {
                name: "replicas_server",
                label: "Number of server replicas",
                kind: "integer",
                default: null,
                values: null,
              },
            ],
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(withParameter),
    );
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    expect(screen.getByTestId("comp-replicas-hint-server")).toHaveTextContent(
      "The driver parameter “Number of server replicas” also sets this count. When both are set, this override applies.",
    );
    expect(screen.getByTestId("comp-replicas-hint-worker")).toHaveTextContent(
      /^Leave empty for no override\.$/,
    );
  });

  it("sends no config when no component has a value", async () => {
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    await user.type(screen.getByLabelText("Deployment Name"), "my-app");
    await user.type(screen.getByTestId("comp-replicas-worker"), "2");
    await user.clear(screen.getByTestId("comp-replicas-worker"));
    await user.click(screen.getByRole("button", { name: "Deploy" }));

    await waitFor(() =>
      expect(noopMutationResult.mutateAsync).toHaveBeenCalledTimes(1),
    );
    expect(noopMutationResult.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ config: null }),
    );
  });

  it("shows the error for a count below 1 and does not deploy", async () => {
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    await user.type(screen.getByLabelText("Deployment Name"), "my-app");
    await user.type(screen.getByTestId("comp-replicas-worker"), "0");

    expect(
      await screen.findByTestId("comp-replicas-error-worker"),
    ).toHaveTextContent(BELOW_ONE);
    expect(screen.getByTestId("comp-replicas-worker")).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Deploy" }));

    expect(noopMutationResult.mutateAsync).not.toHaveBeenCalled();
  });

  it("refuses to deploy a count the backend would reject", async () => {
    await renderPage();
    const user = userEvent.setup();
    await selectVersion(user);

    await user.type(screen.getByLabelText("Deployment Name"), "my-app");
    await user.type(screen.getByTestId("comp-replicas-worker"), "2147483648");
    expect(
      await screen.findByTestId("comp-replicas-error-worker"),
    ).toHaveTextContent("Must be 2147483647 or less.");

    await user.click(screen.getByRole("button", { name: "Deploy" }));

    expect(
      await screen.findByText(
        "Fix the replica count of worker before deploying.",
      ),
    ).toBeInTheDocument();
    expect(noopMutationResult.mutateAsync).not.toHaveBeenCalled();
  });

  it("lists the versions of a driver newest first", async () => {
    const versions: DriversShape = [
      {
        ...drivers[0],
        versions: [
          { ...drivers[0].versions[0], id: "v-simple-9", version: "9" },
          { ...drivers[0].versions[0], id: "v-simple-10", version: "10" },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(versions),
    );
    await renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("driver-version-select"));

    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "simple-app v10@ddddddd",
      "simple-app v9@ddddddd",
    ]);
  });

  it("clears the counts when another driver version is selected", async () => {
    const twoVersions: DriversShape = [
      {
        ...drivers[0],
        versions: [
          drivers[0].versions[0],
          {
            ...drivers[0].versions[0],
            id: "v-simple-5",
            version: "5",
            contentHash: "e".repeat(64),
          },
        ],
      },
    ] as DriversShape;
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(twoVersions),
    );
    await renderPage();
    // The select popup keeps `pointer-events: none` while it reopens.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await selectVersion(user);
    await user.type(screen.getByTestId("comp-replicas-server"), "3");
    expect(screen.getByTestId("comp-replicas-server")).toHaveValue(3);

    await user.click(screen.getByTestId("driver-version-select"));
    await user.click(await screen.findByText("simple-app v5@eeeeeee"));

    await waitFor(() =>
      expect(screen.getByTestId("comp-replicas-server")).toHaveValue(null),
    );
  });
});

describe("DeployFormPage service ingress overrides (#598)", () => {
  const drivers: DriversShape = [
    {
      id: "drv-infrahub",
      name: "infrahub-enterprise",
      versions: [
        {
          id: "v-infrahub-7",
          version: "7",
          supportedVersions: "*",
          defaultVersion: "1.0.0",
          createdOn: "2026-10-01T00:00:00Z",
          contentHash: "f".repeat(64),
          sourceCommitSha: null,
          parameters: [],
          componentConfigs: [{ name: "server", replicas: 2, singleton: false }],
          services: [
            { name: "infrahub", scope: "internal", kind: "http" },
            { name: "task-manager", scope: "external", kind: "http" },
          ],
        },
      ],
    },
  ] as DriversShape;

  beforeEach(() => {
    useListApplicationDriversQueryMock.mockReset();
    useListApplicationDriversQueryMock.mockReturnValue(
      makeQueryResult(drivers),
    );
    noopMutationResult.mutateAsync.mockClear();
  });

  async function selectVersion() {
    await user().click(await screen.findByTestId("driver-version-select"));
    await userEvent
      .setup({ pointerEventsCheck: 0 })
      .click(await screen.findByText("infrahub-enterprise v7@fffffff"));
    await screen.findByRole("group", { name: "Service ingress overrides" });
  }
  const user = () => userEvent.setup({ pointerEventsCheck: 0 });

  it("lists no section until a driver version is selected", async () => {
    await renderPage();

    await screen.findByTestId("driver-version-select");
    expect(
      screen.queryByRole("group", { name: "Service ingress overrides" }),
    ).toBeNull();
  });

  it("offers the fields for an external service and none for an internal one", async () => {
    await renderPage();
    await selectVersion();

    const section = screen.getByRole("group", {
      name: "Service ingress overrides",
    });
    expect(
      within(section).getByLabelText("Ingress class for task-manager"),
    ).toBeInTheDocument();
    expect(
      within(section).getByLabelText("FQDN suffix for task-manager"),
    ).toBeInTheDocument();
    expect(within(section).queryByLabelText(/for infrahub$/)).toBeNull();
  });

  it("sends the override in config.services next to the replica counts", async () => {
    await renderPage();
    await selectVersion();

    await user().type(screen.getByLabelText("Deployment Name"), "my-app");
    await user().type(
      screen.getByLabelText("Ingress class for task-manager"),
      "tailscale",
    );
    await user().type(
      screen.getByLabelText("FQDN suffix for task-manager"),
      "tailnet.example.ts.net",
    );
    await user().type(screen.getByTestId("comp-replicas-server"), "3");
    await user().click(screen.getByRole("button", { name: "Deploy" }));

    await waitFor(() =>
      expect(noopMutationResult.mutateAsync).toHaveBeenCalledTimes(1),
    );
    expect(noopMutationResult.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        config: {
          components: [{ name: "server", replicas: 3 }],
          services: [
            {
              name: "task-manager",
              ingressClass: "tailscale",
              fqdnSuffix: "tailnet.example.ts.net",
            },
          ],
        },
      }),
    );
  });

  it("sends no config when the fields stay empty", async () => {
    await renderPage();
    await selectVersion();

    await user().type(screen.getByLabelText("Deployment Name"), "my-app");
    await user().click(screen.getByRole("button", { name: "Deploy" }));

    await waitFor(() =>
      expect(noopMutationResult.mutateAsync).toHaveBeenCalledTimes(1),
    );
    expect(noopMutationResult.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ config: null }),
    );
  });

  it("disables Deploy and names the service while the suffix is not a DNS name", async () => {
    await renderPage();
    await selectVersion();

    await user().type(
      screen.getByLabelText("FQDN suffix for task-manager"),
      "Bad_Suffix",
    );

    expect(
      screen.getByLabelText("FQDN suffix for task-manager"),
    ).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Deploy" })).toBeDisabled();
    expect(screen.getByTestId("deploy-blocked-reason")).toHaveTextContent(
      "Fix the FQDN suffix of task-manager before deploying.",
    );
  });

  // Regression tests (#598, US4, T053): the form already shows the message of a
  // failed deploy, and a typed refusal of a service ingress override carries the
  // service name in that message.
  it.each([
    [
      "UNKNOWN_SERVICE_INGRESS_OVERRIDE",
      "Ingress override targets service 'web', which driver demo version 1.0.0 does not declare. Known services: [task-manager].",
      "'web'",
    ],
    [
      "SERVICE_INGRESS_NOT_BUILT",
      "Service 'infrahub' has scope 'internal' in driver demo version 1.0.0, so Styrmin does not build its Ingress and an ingress override has no effect. Only a service with scope 'external' can have an ingress override.",
      "'infrahub'",
    ],
    [
      "DUPLICATE_SERVICE_NAME",
      "Service name 'task-manager' appears more than once in the services list; remove the duplicate before submitting.",
      "'task-manager'",
    ],
  ])(
    "shows the message of the %s refusal, which names the service",
    async (code, message, quotedService) => {
      noopMutationResult.mutateAsync.mockRejectedValueOnce(
        new GraphQLOperationError(code, message, { code }),
      );
      await renderPage();
      await selectVersion();
      await user().type(screen.getByLabelText("Deployment Name"), "my-app");

      await user().click(screen.getByRole("button", { name: "Deploy" }));

      const alert = await screen.findByText("Deployment failed");
      const description = alert.parentElement as HTMLElement;
      expect(description).toHaveTextContent(message);
      expect(description).toHaveTextContent(quotedService);
      // The form stays on the page: no "Deployment Submitted" result.
      expect(screen.queryByText("Deployment Submitted")).toBeNull();
    },
  );

  it("disables Deploy and names the service while the ingress class is not a Kubernetes object name", async () => {
    await renderPage();
    await selectVersion();

    await user().type(
      screen.getByLabelText("Ingress class for task-manager"),
      "Bad Class",
    );

    expect(
      screen.getByLabelText("Ingress class for task-manager"),
    ).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Deploy" })).toBeDisabled();
    expect(screen.getByTestId("deploy-blocked-reason")).toHaveTextContent(
      "Fix the ingress class of task-manager before deploying.",
    );
  });
});
