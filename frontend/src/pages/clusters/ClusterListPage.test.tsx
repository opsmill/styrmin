import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/utils";
import ClusterListPage from "./ClusterListPage";

const useListClustersQuery = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListClustersQuery: (...args: unknown[]) => useListClustersQuery(...args),
  };
});

describe("ClusterListPage", () => {
  beforeEach(() => {
    useListClustersQuery.mockReset();
  });

  it("renders a loading state while clusters are loading", async () => {
    useListClustersQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: undefined,
      refetch: vi.fn(),
    });

    await render(<ClusterListPage />);

    expect(screen.getByText(/Loading clusters/i)).toBeInTheDocument();
  });

  it("renders the empty state and the create dialog action when no clusters exist", async () => {
    useListClustersQuery.mockReturnValue({
      data: { clusters: [] },
      isLoading: false,
      error: undefined,
      refetch: vi.fn(),
    });

    await render(<ClusterListPage />);

    expect(screen.getByText("No cluster")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /New Cluster/i }),
    ).toBeInTheDocument();
  });

  it("renders a card per cluster linking to its detail page", async () => {
    useListClustersQuery.mockReturnValue({
      data: {
        clusters: [
          {
            id: "cl-1",
            name: "production",
            config: { ingress_class: "nginx" },
          },
        ],
      },
      isLoading: false,
      error: undefined,
      refetch: vi.fn(),
    });

    await render(<ClusterListPage />);

    const card = screen.getByTestId("cluster-card");
    expect(card).toHaveAttribute("data-cluster-id", "cl-1");
    expect(card).toHaveAttribute("data-cluster-name", "production");
    expect(card).toHaveAttribute("href", "/clusters/cl-1");
    expect(card).toHaveTextContent("production");
    expect(card).toHaveTextContent("Ingress: nginx");
  });

  it("does not show the create dialog action when at least one cluster exists", async () => {
    useListClustersQuery.mockReturnValue({
      data: {
        clusters: [{ id: "cl-1", name: "production", config: {} }],
      },
      isLoading: false,
      error: undefined,
      refetch: vi.fn(),
    });

    await render(<ClusterListPage />);

    expect(
      screen.queryByRole("button", { name: /New Cluster/i }),
    ).not.toBeInTheDocument();
  });
});
