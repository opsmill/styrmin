import { describe, it, expect } from "vitest";
import { render, screen } from "@/test/utils";
import { PhaseChips } from "./PhaseChips";

const NOW = new Date("2026-05-14T12:00:00.000Z");
const polled = new Date(NOW.getTime() - 4 * 1_000).toISOString();

describe("PhaseChips", () => {
  it("counts RUNNING pods that are not ready apart, not in the green running chip (#567)", async () => {
    await render(
      <PhaseChips
        pods={[
          { phase: "RUNNING", ready: true, lastPolledAt: polled },
          { phase: "RUNNING", ready: false, lastPolledAt: polled },
        ]}
        now={NOW}
      />,
    );
    expect(screen.getByTestId("phase-chip-running").textContent).toBe(
      "1 running",
    );
    const notReady = screen.getByTestId("phase-chip-not-ready");
    expect(notReady.textContent).toBe("1 not ready");
    expect(notReady.className).not.toMatch(/emerald/);
  });

  it("shows no green chip when the only RUNNING pod is not ready", async () => {
    await render(
      <PhaseChips
        pods={[{ phase: "RUNNING", ready: false, lastPolledAt: polled }]}
        now={NOW}
      />,
    );
    expect(screen.queryByTestId("phase-chip-running")).not.toBeInTheDocument();
  });
});
