/**
 * DeploymentRow component tests (feature 013 follow-up).
 *
 * Asserts the environment-detail deployments-table row renders the new
 * Driver column: <driverName> on top, v<version>@<short> underneath
 * (font-mono), and the public URL of each component in the Components
 * column (#605). Each row is wrapped in a minimal TanStack Router context
 * because the row holds a <Link> to the deployment.
 */
import { describe, it, expect } from "vitest";
import { render, screen, within, act, waitFor } from "@testing-library/react";
import {
  createRouter,
  createRootRoute,
  createRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

import { DeploymentRow } from "@/pages/environments/EnvironmentDetailPage";

type Deployment = React.ComponentProps<typeof DeploymentRow>["deployment"];

function makeDeployment(overrides: Partial<Deployment> = {}): Deployment {
  return {
    id: "dep-1",
    name: "web",
    status: "active",
    applicationVersion: "2.5.0",
    applicationDriverVersion: {
      version: "1.2.3",
      contentHash: "a".repeat(64),
      sourceCommitSha: null,
      applicationDriver: { name: "nginx" },
    },
    components: [{ id: "c-1", name: "server", enabled: true }],
    deployedServices: [],
    deletedAt: null,
    ...overrides,
  };
}

async function renderRow(deployment: Deployment) {
  const rootRoute = createRootRoute();
  const envRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId",
    component: () => (
      <DeploymentRow deployment={deployment} environmentId="env-1" index={0} />
    ),
  });
  const depRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/environments/$environmentId/deployments/$deploymentId",
    component: () => <div>deployment detail</div>,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([envRoute, depRoute]),
    history: createMemoryHistory({ initialEntries: ["/environments/env-1"] }),
  });
  await router.load();
  await act(async () => {
    render(<RouterProvider router={router} />);
  });
  await waitFor(() => {
    expect(screen.getByTestId("deployment-driver-cell")).toBeInTheDocument();
  });
}

describe("DeploymentRow Driver column", () => {
  it("renders <driverName> and v<version>@<short-contentHash> for a local-source deployment", async () => {
    const deployment = makeDeployment({
      applicationDriverVersion: {
        version: "1.2.3",
        contentHash: "a".repeat(64),
        sourceCommitSha: null,
        applicationDriver: { name: "nginx" },
      },
    });

    await renderRow(deployment);

    const cell = screen.getByTestId("deployment-driver-cell");
    expect(within(cell).getByText("nginx")).toBeInTheDocument();
    expect(within(cell).getByText("v1.2.3@aaaaaaa")).toBeInTheDocument();
  });

  it("renders <driverName> and v<version>@<short-sourceCommitSha> for a git-source deployment", async () => {
    const deployment = makeDeployment({
      applicationDriverVersion: {
        version: "2.0.0",
        contentHash: null,
        sourceCommitSha: "b".repeat(40),
        applicationDriver: { name: "redis" },
      },
    });

    await renderRow(deployment);

    const cell = screen.getByTestId("deployment-driver-cell");
    expect(within(cell).getByText("redis")).toBeInTheDocument();
    expect(within(cell).getByText("v2.0.0@bbbbbbb")).toBeInTheDocument();
  });

  it("renders the em-dash placeholder when applicationDriverVersion is null", async () => {
    const deployment = makeDeployment({
      applicationDriverVersion: null,
    });

    await renderRow(deployment);

    const cell = screen.getByTestId("deployment-driver-cell");
    expect(within(cell).getByText("—")).toBeInTheDocument();
    // No driver name / formatted label leaks in.
    expect(within(cell).queryByText("nginx")).not.toBeInTheDocument();
    expect(within(cell).queryByText(/^v\d/)).not.toBeInTheDocument();
  });
});

describe("DeploymentRow component public URLs (#605)", () => {
  const services: Deployment["deployedServices"] = [
    {
      id: "svc-1",
      component: "server",
      humanReadableUrl: "https://web-prod.example.com",
    },
    {
      id: "svc-2",
      component: "task-manager",
      humanReadableUrl: "https://task-manager-prod.example.com:8443",
    },
  ];
  const components: Deployment["components"] = [
    { id: "c-1", name: "server", enabled: true },
    { id: "c-2", name: "task-manager", enabled: true },
    { id: "c-3", name: "worker", enabled: true },
  ];

  it("lists each component's public URL as a link that opens in a new tab", async () => {
    await renderRow(makeDeployment({ components, deployedServices: services }));

    const cell = screen.getByTestId("deployment-components-cell");
    expect(within(cell).getByText("3 components")).toBeInTheDocument();

    const entries = within(cell).getAllByTestId("component-public-url");
    expect(entries.map((entry) => entry.dataset.component)).toEqual([
      "server",
      "task-manager",
    ]);

    const serverLink = within(entries[0]).getByRole("link", {
      name: /web-prod\.example\.com/,
    });
    expect(serverLink).toHaveAttribute("href", "https://web-prod.example.com");
    expect(serverLink).toHaveAttribute("target", "_blank");
    expect(serverLink).toHaveAttribute("rel", "noreferrer noopener");
    // The line break opportunities add no character to the URL text.
    expect(serverLink.textContent).toBe("https://web-prod.example.com");
    expect(within(entries[0]).getByText("server")).toBeInTheDocument();

    expect(
      within(entries[1]).getByRole("link", {
        name: /task-manager-prod\.example\.com:8443/,
      }),
    ).toHaveAttribute("href", "https://task-manager-prod.example.com:8443");
  });

  it("keeps the deployment name as the link to the deployment, and does not nest the URL links in it", async () => {
    await renderRow(makeDeployment({ components, deployedServices: services }));

    const rowLink = screen.getByTestId("deployment-row-link");
    expect(rowLink).toHaveAttribute(
      "href",
      "/environments/env-1/deployments/dep-1",
    );
    expect(rowLink).toHaveTextContent("web");
    for (const urlLink of within(
      screen.getByTestId("deployment-components-cell"),
    ).getAllByRole("link")) {
      expect(urlLink.parentElement?.closest("a")).toBeNull();
    }
  });

  it("leaves out a service that has no public URL", async () => {
    await renderRow(
      makeDeployment({
        components,
        deployedServices: [
          { id: "svc-1", component: "server", humanReadableUrl: null },
        ],
      }),
    );

    expect(screen.queryAllByTestId("component-public-url")).toHaveLength(0);
    expect(screen.getByText("3 components")).toBeInTheDocument();
  });

  it("marks the URL of a disabled component", async () => {
    await renderRow(
      makeDeployment({
        components: [
          { id: "c-1", name: "server", enabled: true },
          { id: "c-2", name: "task-manager", enabled: false },
        ],
        deployedServices: services,
      }),
    );

    const [server, taskManager] = screen.getAllByTestId("component-public-url");
    expect(within(server).queryByText("(disabled)")).not.toBeInTheDocument();
    expect(within(taskManager).getByText("(disabled)")).toBeInTheDocument();
  });

  it.each([
    { status: "deleting", deletedAt: null },
    { status: "deleted", deletedAt: "2026-11-16T10:00:00Z" },
  ])(
    "shows no public URL for a deployment whose status is $status",
    async ({ status, deletedAt }) => {
      await renderRow(
        makeDeployment({
          status,
          deletedAt,
          components,
          deployedServices: services,
        }),
      );

      expect(screen.queryAllByTestId("component-public-url")).toHaveLength(0);
    },
  );
});
