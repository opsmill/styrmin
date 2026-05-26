/**
 * DeploymentRow component tests (feature 013 follow-up).
 *
 * Asserts the environment-detail deployments-table row renders the new
 * Driver column: <driverName> on top, v<version>@<short> underneath
 * (font-mono). Each row is wrapped in a minimal TanStack Router context
 * because the row is a <Link>.
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
    components: [{ id: "c-1" }],
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
