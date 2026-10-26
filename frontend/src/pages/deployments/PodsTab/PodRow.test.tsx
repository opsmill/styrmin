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
