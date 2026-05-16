import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
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

  it("renders the global namespace strip above the section list", async () => {
    useGetDeploymentPodsQuery.mockReturnValue({
      data: { podStatuses: [] },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
      dataUpdatedAt: Date.now(),
    });

    await render(
      <PodsTab
        {...baseProps}
        deploymentId="abc-123"
        deploymentStatus="creating"
      />,
    );

    const strip = screen.getByTestId("pods-namespace-strip");
    expect(strip).toBeInTheDocument();
    expect(screen.getByTestId("pods-namespace-value")).toHaveTextContent(
      "styrmin-abc-123",
    );
    expect(screen.getByTestId("copy-namespace-button")).toBeInTheDocument();
  });

  it("renders all-healthy declared sections collapsed by default; click expands them", async () => {
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
    // Both declared sections (1 healthy pod, 1 empty) start collapsed.
    expect(sections[0]).toHaveAttribute("data-open", "false");
    expect(sections[1]).toHaveAttribute("data-open", "false");
    // Empty placeholder is not in the DOM while collapsed; the chip
    // summary "no pods" is the only signal.
    expect(
      screen.queryByText(/No pods reported for this component/i),
    ).not.toBeInTheDocument();

    // Clicking the api header expands it.
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /Expand api section/i }),
    );
    expect(screen.getAllByTestId("pod-section")[0]).toHaveAttribute(
      "data-open",
      "true",
    );
  });

  it("auto-expands sections with anything not RUNNING/ready/fresh", async () => {
    useGetDeploymentPodsQuery.mockReturnValue({
      data: {
        podStatuses: [
          {
            id: "p1",
            podName: "api-bad",
            namespace: "ns",
            phase: "PENDING",
            ready: false,
            restartCount: 0,
            nodeName: null,
            componentName: "api",
            startedAt: null,
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
        declaredComponents={[{ name: "api" }]}
        deploymentStatus="running"
      />,
    );

    expect(screen.getByTestId("pod-section")).toHaveAttribute(
      "data-open",
      "true",
    );
  });
});
