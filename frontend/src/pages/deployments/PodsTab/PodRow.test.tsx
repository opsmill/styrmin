import { describe, it, expect } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
import { PodRow } from "./PodRow";
import type { GetDeploymentPodsQuery } from "@/generated/graphql";

type Pod = GetDeploymentPodsQuery["podStatuses"][number];

const NOW = new Date("2026-05-14T12:00:00.000Z");
const TWO_HOURS_AGO = new Date(
  NOW.getTime() - 2 * 60 * 60 * 1_000,
).toISOString();
const ONE_MINUTE_AGO = new Date(NOW.getTime() - 60 * 1_000).toISOString();
const FOUR_SECONDS_AGO = new Date(NOW.getTime() - 4 * 1_000).toISOString();

function makePod(overrides: Partial<Pod> = {}): Pod {
  return {
    id: "pod-1",
    podName: "api-7f9d4-jh2bn",
    namespace: "styrmin-api-gateway-prod",
    phase: "RUNNING",
    ready: true,
    restartCount: 0,
    nodeName: "ip-10-0-2-47",
    componentName: "api",
    startedAt: TWO_HOURS_AGO,
    createdOn: TWO_HOURS_AGO,
    lastPolledAt: FOUR_SECONDS_AGO,
    containerStatuses: [
      {
        name: "api",
        image: "ghcr.io/acme/api:v2.4.1",
        ready: true,
        state: "running",
        restart_count: 0,
      },
    ] as unknown as Record<string, unknown>,
    ...overrides,
  };
}

describe("PodRow", () => {
  it("toggles expansion when the row is clicked", async () => {
    await render(<PodRow pod={makePod()} now={NOW} />);
    expect(screen.queryByText("Commands")).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /api-7f9d4-jh2bn/i }));
    expect(screen.getByText("Commands")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /api-7f9d4-jh2bn/i }));
    expect(screen.queryByText("Commands")).not.toBeInTheDocument();
  });

  it("shows a RUNNING pod that is not ready as NOT READY, not green (#567)", async () => {
    const { container } = await render(
      <PodRow pod={makePod({ ready: false, restartCount: 3 })} now={NOW} />,
    );
    const badge = container.querySelector('[data-pod-phase="RUNNING"]');
    expect(badge?.textContent).toBe("NOT READY");
    expect(badge?.className).not.toMatch(/emerald/);
  });

  it("shows a RUNNING pod that is ready as RUNNING, in green", async () => {
    const { container } = await render(<PodRow pod={makePod()} now={NOW} />);
    const badge = container.querySelector('[data-pod-phase="RUNNING"]');
    expect(badge?.textContent).toBe("RUNNING");
    expect(badge?.className).toMatch(/emerald/);
  });

  it("renders the stale indicator when lastPolledAt is older than 30s", async () => {
    await render(
      <PodRow pod={makePod({ lastPolledAt: ONE_MINUTE_AGO })} now={NOW} />,
    );
    expect(screen.getByTestId("stale-indicator")).toBeInTheDocument();
  });

  it("does not render the stale indicator when polled recently", async () => {
    await render(<PodRow pod={makePod()} now={NOW} />);
    expect(screen.queryByTestId("stale-indicator")).not.toBeInTheDocument();
  });

  it("renders the expected logs kubectl command string in the Commands section", async () => {
    // The actual clipboard write is exercised by useCopyToClipboard's own
    // test; here we only verify PodRow surfaces the same string Copy would
    // place in the clipboard.
    await render(<PodRow pod={makePod()} now={NOW} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /api-7f9d4-jh2bn/i }));
    await user.click(screen.getByRole("button", { name: /Commands/i }));
    expect(
      await screen.findByText(
        "kubectl logs --namespace styrmin-api-gateway-prod api-7f9d4-jh2bn --all-containers",
      ),
    ).toBeInTheDocument();
  });
});

describe("PodRow failure causes (#574)", () => {
  async function expand(pod: Pod) {
    await render(<PodRow pod={pod} now={NOW} />);
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: new RegExp(pod.podName) }),
    );
  }

  it("shows why a pod is not scheduled", async () => {
    await expand(
      makePod({
        phase: "PENDING",
        ready: false,
        nodeName: null,
        startedAt: null,
        containerStatuses: [
          {
            name: "PodScheduled",
            kind: "pod",
            ready: false,
            state: "waiting:Unschedulable",
            message:
              "0/2 nodes are available: pod has unbound immediate PersistentVolumeClaims. not found",
            restart_count: 0,
            image: "",
            started_at: null,
          },
        ] as unknown as Record<string, unknown>,
      }),
    );

    const notice = screen.getByTestId("pod-condition");
    expect(notice).toHaveTextContent("Not scheduled: Unschedulable");
    expect(notice).toHaveTextContent(
      "0/2 nodes are available: pod has unbound immediate PersistentVolumeClaims. not found",
    );
    // The pod entry is not a container.
    expect(screen.queryByTestId("container-row")).not.toBeInTheDocument();
    expect(
      screen.getByText("No container statuses reported yet."),
    ).toBeInTheDocument();
  });

  it("lists a failing init container before the container, with its restarts", async () => {
    await expand(
      makePod({
        phase: "PENDING",
        ready: false,
        restartCount: 5,
        containerStatuses: [
          {
            name: "admin",
            kind: "init",
            ready: false,
            state: "waiting:CrashLoopBackOff",
            message: "back-off 2m40s restarting failed container=admin",
            restart_count: 5,
            image: "docker.io/semaphoreui/semaphore:v2.16.47",
            started_at: null,
          },
          {
            name: "semaphore",
            kind: "container",
            ready: false,
            state: "waiting:PodInitializing",
            message: null,
            restart_count: 0,
            image: "semaphoreui/semaphore:v2.16.47",
            started_at: null,
          },
        ] as unknown as Record<string, unknown>,
      }),
    );

    const rows = screen.getAllByTestId("container-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("admin");
    expect(rows[0]).toHaveTextContent("init");
    expect(rows[0]).toHaveTextContent("5");
    expect(rows[0]).toHaveTextContent("waiting: CrashLoopBackOff");
    expect(rows[1]).toHaveTextContent("semaphore");
    expect(rows[1]).not.toHaveTextContent("init");
    expect(screen.queryByTestId("pod-condition")).not.toBeInTheDocument();
  });

  it("marks a sidecar as a sidecar, not as an init container", async () => {
    // A sidecar is an init container with `restartPolicy: Always` that runs next
    // to the containers; this one fails its readiness probe.
    await expand(
      makePod({
        containerStatuses: [
          {
            name: "proxy",
            kind: "sidecar",
            ready: false,
            state: "running",
            message: null,
            restart_count: 0,
            image: "docker.io/library/busybox:1.36",
            started_at: "2026-10-27T11:36:55+00:00",
          },
          {
            name: "app",
            kind: "container",
            ready: true,
            state: "running",
            message: null,
            restart_count: 0,
            image: "docker.io/library/busybox:1.36",
            started_at: "2026-10-27T11:36:55+00:00",
          },
        ] as unknown as Record<string, unknown>,
      }),
    );

    const rows = screen.getAllByTestId("container-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("proxy");
    expect(rows[0]).toHaveTextContent("sidecar");
    expect(rows[0]).not.toHaveTextContent("init");
    expect(rows[1]).toHaveTextContent("app");
    expect(rows[1]).not.toHaveTextContent("sidecar");
  });

  it("shows the kubelet message under the container", async () => {
    const message =
      'Back-off pulling image "traefik/whoami:v1.99.99": ErrImagePull: not found';
    await expand(
      makePod({
        phase: "PENDING",
        ready: false,
        containerStatuses: [
          {
            name: "app",
            kind: "container",
            ready: false,
            state: "waiting:ImagePullBackOff",
            message,
            restart_count: 0,
            image: "traefik/whoami:v1.99.99",
            started_at: null,
          },
        ] as unknown as Record<string, unknown>,
      }),
    );

    expect(screen.getByTestId("container-message")).toHaveTextContent(message);
  });

  it("shows an entry without a kind as a container", async () => {
    // Rows stored by an agent older than #574 have no kind and no message.
    await expand(makePod());

    const [row] = screen.getAllByTestId("container-row");
    expect(row).toHaveTextContent("api");
    expect(row).not.toHaveTextContent("init");
    expect(screen.queryByTestId("container-message")).not.toBeInTheDocument();
  });
});
