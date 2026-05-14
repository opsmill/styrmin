import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/utils";
import { PodsTab } from "./PodsTab";

// Mock the generated hook so each test can control the query state.
const useGetDeploymentPodsQuery = vi.fn();
vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useGetDeploymentPodsQuery: (...args: unknown[]) =>
      useGetDeploymentPodsQuery(...args),
  };
});

const baseProps = {
  deploymentId: "deployment-1",
  isActive: true,
  declaredComponents: [{ name: "api" }],
  onOpenTimeline: vi.fn(),
};

describe("PodsTab", () => {
  beforeEach(() => {
    useGetDeploymentPodsQuery.mockReset();
  });

  it("shows the RUNNING empty state with a Timeline link when the deployment is running but no pods reported", async () => {
    useGetDeploymentPodsQuery.mockReturnValue({
      data: { podStatuses: [] },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    });

    const onOpenTimeline = vi.fn();
    await render(
      <PodsTab
        {...baseProps}
        deploymentStatus="running"
        onOpenTimeline={onOpenTimeline}
      />,
    );

    const empty = screen.getByTestId("pods-empty-state");
    expect(empty).toHaveAttribute("data-deployment-status", "running");
    expect(empty).toHaveTextContent(/no pods have been reported/i);
    expect(empty).toHaveTextContent(/check the Timeline tab/i);
    expect(
      screen.getByRole("button", { name: /Open Timeline/i }),
    ).toBeInTheDocument();
  });

  it("shows the non-RUNNING empty state explaining the current phase", async () => {
    useGetDeploymentPodsQuery.mockReturnValue({
      data: { podStatuses: [] },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    });

    await render(<PodsTab {...baseProps} deploymentStatus="creating" />);

    const empty = screen.getByTestId("pods-empty-state");
    expect(empty).toHaveAttribute("data-deployment-status", "creating");
    expect(empty).toHaveTextContent(/current deployment phase/i);
    expect(empty).toHaveTextContent(/creating/i);
    expect(
      screen.queryByRole("button", { name: /Open Timeline/i }),
    ).not.toBeInTheDocument();
  });

  it("renders declared sections (including empty ones) when the deployment has pods", async () => {
    useGetDeploymentPodsQuery.mockReturnValue({
      data: {
        podStatuses: [
          {
            id: "p1",
            podName: "api-abc-123",
            namespace: "ns",
            phase: "RUNNING",
            ready: true,
            restartCount: 0,
            nodeName: "node-1",
            componentName: "api",
            startedAt: new Date().toISOString(),
            createdOn: new Date().toISOString(),
            lastPolledAt: new Date().toISOString(),
            containerStatuses: [],
          },
        ],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    });

    await render(
      <PodsTab
        {...baseProps}
        declaredComponents={[{ name: "api" }, { name: "worker" }]}
        deploymentStatus="running"
      />,
    );

    const sections = screen.getAllByTestId("pod-section");
    expect(sections).toHaveLength(2);
    expect(sections[0]).toHaveAttribute("data-variant", "declared");
    expect(sections[0]).toHaveAttribute("data-component", "api");
    expect(sections[1]).toHaveAttribute("data-component", "worker");
    expect(sections[1]).toHaveTextContent(
      /No pods reported for this component/i,
    );
  });
});
