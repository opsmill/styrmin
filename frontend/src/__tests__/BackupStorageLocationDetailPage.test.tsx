import { describe, it, expect, afterEach, vi } from "vitest";
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

import BackupStorageLocationDetailPage from "@/pages/backup-storage-locations/BackupStorageLocationDetailPage";

vi.mock("@/auth/IfRole", () => ({
  IfRole: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const BSL_ID = "b-1";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface FetchBody {
  query?: string;
}

/**
 * Serve the location query at once. The delete mutation stays pending until
 * `finishDelete` is called, then answers with `deleteResponse`.
 */
function installFetch(deleteResponse: Response) {
  let finishDelete: () => void = () => {};
  const deleteGate = new Promise<void>((resolve) => {
    finishDelete = resolve;
  });
  const fetchMock = vi.fn(async (_url: unknown, init?: RequestInit) => {
    const body: FetchBody = init?.body
      ? (JSON.parse(init.body as string) as FetchBody)
      : {};
    const query = body.query ?? "";
    if (query.includes("mutation DeleteBackupStorageLocation")) {
      await deleteGate;
      return deleteResponse;
    }
    return jsonResponse({
      data: {
        backupStorageLocation: {
          id: BSL_ID,
          name: "offsite",
          endpoint: "https://s3.example.com",
          bucket: "backups",
          region: "us-east-1",
          createdOn: "2025-01-01T00:00:00Z",
          updatedOn: null,
          environmentCount: 0,
        },
      },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, finishDelete: () => finishDelete() };
}

function deleteCalls(fetchMock: ReturnType<typeof vi.fn>): number {
  return fetchMock.mock.calls.filter(([, init]) =>
    String((init as RequestInit | undefined)?.body).includes(
      "mutation DeleteBackupStorageLocation",
    ),
  ).length;
}

async function renderDetailPage(): Promise<void> {
  const rootRoute = createRootRoute();
  const listRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/backup-storage-locations",
    component: () => <div>locations list</div>,
  });
  const detailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/backup-storage-locations/$id",
    component: () => <BackupStorageLocationDetailPage />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([listRoute, detailRoute]),
    history: createMemoryHistory({
      initialEntries: [`/backup-storage-locations/${BSL_ID}`],
    }),
  });
  await router.load();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  await act(async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  });
}

describe("BackupStorageLocationDetailPage — delete", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("disables the Delete button and shows progress until the delete returns", async () => {
    const { fetchMock, finishDelete } = installFetch(
      jsonResponse({
        data: {
          deleteBackupStorageLocation: "Backup storage location deleted",
        },
      }),
    );
    await renderDetailPage();
    const user = userEvent.setup();

    const button = await screen.findByRole("button", { name: /^Delete$/ });
    await user.click(button);

    const pending = await screen.findByRole("button", { name: /Deleting/ });
    expect(pending).toBeDisabled();
    // A second click sends no second delete.
    await user.click(pending);
    expect(deleteCalls(fetchMock)).toBe(1);

    await act(async () => finishDelete());
    await waitFor(() => {
      expect(screen.getByText("locations list")).toBeInTheDocument();
    });
  });

  it("enables the Delete button again and shows the refusal when the delete fails", async () => {
    const { finishDelete } = installFetch(
      jsonResponse({
        data: { deleteBackupStorageLocation: null },
        errors: [
          {
            message:
              "Could not submit the removal of backup storage location 'offsite' to Prefect; it was not deleted.",
            path: ["deleteBackupStorageLocation"],
            extensions: { code: "OPERATION_FAILED" },
          },
        ],
      }),
    );
    await renderDetailPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /^Delete$/ }));
    await screen.findByRole("button", { name: /Deleting/ });
    await act(async () => finishDelete());

    expect(await screen.findByText("Cannot Delete")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Could not submit the removal of backup storage location/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Delete$/ })).toBeEnabled();
  });
});
