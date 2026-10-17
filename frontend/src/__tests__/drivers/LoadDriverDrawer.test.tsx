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
import { Toaster } from "@/components/ui/toast";
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
          <Toaster>
            <RouterProvider router={router} />
          </Toaster>
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

  it("sends the driver directory when one is entered", async () => {
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
    await user.type(screen.getByLabelText("Driver directory"), "drivers/a");
    await user.click(screen.getByRole("button", { name: /^load driver$/i }));
    await waitFor(() => {
      expect(loadRemoteMutateAsync).toHaveBeenCalledTimes(1);
    });
    expect(loadRemoteMutateAsync.mock.calls[0][0]).toStrictEqual({
      repositoryUrl: "https://github.com/org/repo",
      branch: "main",
      driverDirectory: "drivers/a",
    });
  });

  it.each([
    ["empty", ""],
    ["spaces only", "   "],
  ])(
    "sends no driver directory when the field is %s",
    async (_case, entered) => {
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
      if (entered) {
        await user.type(screen.getByLabelText("Driver directory"), entered);
      }
      await user.click(screen.getByRole("button", { name: /^load driver$/i }));
      await waitFor(() => {
        expect(loadRemoteMutateAsync).toHaveBeenCalledTimes(1);
      });
      expect(loadRemoteMutateAsync.mock.calls[0][0]).toStrictEqual({
        repositoryUrl: "https://github.com/org/repo",
        branch: "main",
      });
    },
  );

  it("shows the load error and keeps the entered values when the load fails", async () => {
    const error =
      "Driver directory 'drivers/a' does not exist in repository " +
      "'https://github.com/org/repo' (branch 'release', commit " +
      "0123456789abcdef0123456789abcdef01234567).";
    loadRemoteMutateAsync.mockRejectedValue(new Error(error));
    await renderDrawer();
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Repository URL"),
      "https://github.com/org/repo",
    );
    await user.clear(screen.getByLabelText("Branch"));
    await user.type(screen.getByLabelText("Branch"), "release");
    await user.type(screen.getByLabelText("Driver directory"), "drivers/a");
    await user.click(screen.getByRole("button", { name: /^load driver$/i }));

    expect(await screen.findByText(error)).toBeInTheDocument();
    expect(screen.getByText("Couldn't load the driver")).toBeInTheDocument();
    expect(screen.getByLabelText("Repository URL")).toHaveValue(
      "https://github.com/org/repo",
    );
    expect(screen.getByLabelText("Branch")).toHaveValue("release");
    expect(screen.getByLabelText("Driver directory")).toHaveValue("drivers/a");
  });

  it("navigates to the new version's detail page and toasts on success", async () => {
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

    // The drawer auto-navigates to the detail route (rendered as "detail")…
    await waitFor(() => {
      expect(screen.getByText("detail")).toBeInTheDocument();
    });
    // …and raises a success toast naming the loaded version.
    expect(screen.getByText("Driver loaded")).toBeInTheDocument();
    expect(screen.getByText(/version 2\.1\.0/i)).toBeInTheDocument();
  });

  it("lists the load warnings in a toast that stays until dismissed", async () => {
    const warning =
      "spec.info.icon must be an absolute https URL, such as " +
      "https://example.com/logo.svg (found 'xxxx'). The icon was not stored.";
    loadLocalMutateAsync.mockResolvedValue({
      loadLocalApplicationDriverVersion: {
        id: "v1",
        applicationDriverId: "d1",
        version: "2.1.0",
        loadWarnings: [warning],
      },
    });
    await renderDrawer();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Local directory" }));
    await user.type(screen.getByLabelText("Directory path"), "/opt/drivers/x");
    await user.click(screen.getByRole("button", { name: /^load driver$/i }));

    await waitFor(() => {
      expect(screen.getByText("detail")).toBeInTheDocument();
    });
    expect(screen.getByText("Driver loaded with warnings")).toBeInTheDocument();
    expect(screen.queryByText("Driver loaded")).not.toBeInTheDocument();
    expect(screen.getByText(/version 2\.1\.0/i)).toHaveTextContent(
      `• ${warning}`,
    );
  });

  it("shows each line of a load error on its own line", async () => {
    loadRemoteMutateAsync.mockRejectedValue(
      new Error(
        "The driver specification is invalid:\n- spec.version: Field required",
      ),
    );
    await renderDrawer();
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Repository URL"),
      "https://github.com/org/repo",
    );
    await user.click(screen.getByRole("button", { name: /^load driver$/i }));

    const message = await screen.findByText(/spec\.version: Field required/);
    expect(message).toHaveClass("whitespace-pre-line");
  });
});
