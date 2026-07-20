import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRouter,
  createRootRoute,
  createRoute,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

import { ThemeProvider } from "@/hooks/use-theme";
import { LoadDriverDrawer } from "@/pages/drivers/LoadDriverDrawer";

const loadRemoteMutateAsync = vi.fn();
const loadLocalMutateAsync = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useLoadRemoteDriverMutation: () => ({ mutateAsync: loadRemoteMutateAsync }),
    useLoadLocalDriverMutation: () => ({ mutateAsync: loadLocalMutateAsync }),
  };
});

function makeRouter() {
  const rootRoute = createRootRoute();
  const listRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers",
    component: () => <LoadDriverDrawer open onOpenChange={() => {}} />,
  });
  const detailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/drivers/$driverId",
    validateSearch: (s: Record<string, unknown>) => ({
      version: typeof s.version === "string" ? s.version : undefined,
    }),
    component: () => <div>detail</div>,
  });
  return createRouter({
    routeTree: rootRoute.addChildren([listRoute, detailRoute]),
    history: createMemoryHistory({ initialEntries: ["/drivers"] }),
  });
}

async function renderDrawer() {
  const router = makeRouter();
  await router.load();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });
}

describe("LoadDriverDrawer", () => {
  beforeEach(() => {
    loadRemoteMutateAsync.mockReset();
    loadLocalMutateAsync.mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it("opens on the Git tab with repository and branch fields", async () => {
    await renderDrawer();
    expect(screen.getByText("Load a driver")).toBeInTheDocument();
    expect(screen.getByLabelText("Repository URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Branch")).toBeInTheDocument();
  });

  it("switches to the Local directory tab and shows the path field", async () => {
    await renderDrawer();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /local directory/i }));
    expect(screen.getByLabelText("Directory path")).toBeInTheDocument();
  });

  it("shows a validation error when submitting an empty Git form", async () => {
    await renderDrawer();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^load driver$/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/repository url is required/i),
      ).toBeInTheDocument();
    });
    expect(loadRemoteMutateAsync).not.toHaveBeenCalled();
  });

  it("calls the remote load mutation with the entered values", async () => {
    loadRemoteMutateAsync.mockResolvedValue({
      loadRemoteApplicationDriverVersion: {
        id: "v1",
        applicationDriverId: "d1",
      },
    });
    await renderDrawer();
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Repository URL"),
      "https://github.com/org/repo",
    );
    await user.click(screen.getByRole("button", { name: /^load driver$/i }));
    await waitFor(() => {
      expect(loadRemoteMutateAsync).toHaveBeenCalledWith({
        repositoryUrl: "https://github.com/org/repo",
        branch: "main",
      });
    });
  });

  it("shows a success confirmation after loading, with a View driver action", async () => {
    loadRemoteMutateAsync.mockResolvedValue({
      loadRemoteApplicationDriverVersion: {
        id: "v1",
        applicationDriverId: "d1",
        version: "2.1.0",
      },
    });
    await renderDrawer();
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Repository URL"),
      "https://github.com/org/repo",
    );
    await user.click(screen.getByRole("button", { name: /^load driver$/i }));
    await waitFor(() => {
      expect(screen.getByText("Driver loaded")).toBeInTheDocument();
    });
    expect(screen.getByText("2.1.0")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /view driver/i }),
    ).toBeInTheDocument();
  });
});
