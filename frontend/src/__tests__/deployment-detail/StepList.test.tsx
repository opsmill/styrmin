/**
 * StepList rows (spec 019-task-steps, US1): status icon with a text label,
 * name, duration or "running for <elapsed>", and the attempt count above 1.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "@testing-library/react";
import { render, screen, within } from "@/test/utils";
import { StepList, type StepListItem } from "@/components/deployment/StepList";
import type { StepStatus } from "@/generated/graphql";

function makeStep(overrides: Partial<StepListItem> = {}): StepListItem {
  return {
    id: "step-1",
    key: "plan",
    name: "Plan the changes",
    kind: "PLAN",
    status: "SUCCEEDED",
    startedAt: "2026-10-06T10:00:00+00:00",
    endedAt: "2026-10-06T10:00:04+00:00",
    durationSeconds: 4.2,
    attemptCount: 1,
    hasOutput: false,
    ...overrides,
  };
}

function rows(): HTMLElement[] {
  return screen.getAllByTestId("step-row");
}

afterEach(() => {
  vi.useRealTimers();
});

describe("StepList", () => {
  it.each<[StepStatus, string]>([
    ["PENDING", "Pending"],
    ["RUNNING", "Running"],
    ["SUCCEEDED", "Succeeded"],
    ["FAILED", "Failed"],
    ["SUPERSEDED", "Superseded"],
  ])("shows %s with the text label %s", async (status, label) => {
    await render(<StepList steps={[makeStep({ status })]} />);

    const [row] = rows();
    expect(row).toHaveAttribute("data-step-status", status);
    expect(within(row).getByTestId("step-status")).toHaveTextContent(label);
  });

  it("lists the steps in the given order with their keys and names", async () => {
    await render(
      <StepList
        steps={[
          makeStep({ id: "a", key: "plan", name: "Plan the changes" }),
          makeStep({
            id: "b",
            key: "resource:styrmindeployment",
            name: "Write the StyrminDeployment resource",
            kind: "RESOURCE_WRITE",
          }),
          makeStep({
            id: "c",
            key: "operator:prerequisites",
            name: "Create network policies and secrets",
            kind: "OPERATOR_PHASE",
            status: "PENDING",
            startedAt: null,
            endedAt: null,
            durationSeconds: null,
          }),
        ]}
      />,
    );

    expect(rows().map((row) => row.getAttribute("data-step-key"))).toEqual([
      "plan",
      "resource:styrmindeployment",
      "operator:prerequisites",
    ]);
    expect(
      screen.getAllByTestId("step-name").map((name) => name.textContent),
    ).toEqual([
      "Plan the changes",
      "Write the StyrminDeployment resource",
      "Create network policies and secrets",
    ]);
  });

  it("exposes the step fields as data attributes", async () => {
    await render(
      <StepList
        steps={[
          makeStep({
            id: "step-9",
            key: "hook:upgrade:core",
            kind: "HOOK",
            status: "FAILED",
            attemptCount: 2,
            hasOutput: true,
          }),
        ]}
      />,
    );

    const [row] = rows();
    expect(row).toHaveAttribute("data-step-id", "step-9");
    expect(row).toHaveAttribute("data-step-key", "hook:upgrade:core");
    expect(row).toHaveAttribute("data-step-kind", "HOOK");
    expect(row).toHaveAttribute("data-step-status", "FAILED");
    expect(row).toHaveAttribute(
      "data-step-started-at",
      "2026-10-06T10:00:00+00:00",
    );
    expect(row).toHaveAttribute(
      "data-step-ended-at",
      "2026-10-06T10:00:04+00:00",
    );
    expect(row).toHaveAttribute("data-step-attempts", "2");
    expect(row).toHaveAttribute("data-step-has-output", "true");
  });

  it.each<[number, string]>([
    [0.3, "<1s"],
    [4.2, "4s"],
    [65, "1m 05s"],
    [3720, "1h 02m"],
  ])("shows a duration of %s seconds as %s", async (seconds, text) => {
    await render(<StepList steps={[makeStep({ durationSeconds: seconds })]} />);

    expect(screen.getByTestId("step-duration")).toHaveTextContent(text);
  });

  it("shows the elapsed time of a running step and updates it", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-10-06T10:01:30+00:00"));

    await render(
      <StepList
        steps={[
          makeStep({
            status: "RUNNING",
            startedAt: "2026-10-06T10:00:00+00:00",
            endedAt: null,
            durationSeconds: null,
          }),
        ]}
      />,
    );

    expect(screen.getByTestId("step-duration")).toHaveTextContent(
      "running for 1m 30s",
    );

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(screen.getByTestId("step-duration")).toHaveTextContent(
      "running for 1m 40s",
    );
  });

  it("shows no duration for a pending step", async () => {
    await render(
      <StepList
        steps={[
          makeStep({
            status: "PENDING",
            startedAt: null,
            endedAt: null,
            durationSeconds: null,
          }),
        ]}
      />,
    );

    expect(screen.queryByTestId("step-duration")).not.toBeInTheDocument();
  });

  it("shows the attempt count only when it is above 1", async () => {
    await render(
      <StepList
        steps={[
          makeStep({ id: "once", key: "once", attemptCount: 1 }),
          makeStep({
            id: "thrice",
            key: "operator:prerequisites",
            status: "FAILED",
            attemptCount: 3,
          }),
        ]}
      />,
    );

    const [once, thrice] = rows();
    expect(within(once).queryByTestId("step-attempts")).not.toBeInTheDocument();
    expect(within(thrice).getByTestId("step-attempts")).toHaveTextContent(
      "3 attempts",
    );
  });

  it("renders nothing for an empty list", async () => {
    await render(<StepList steps={[]} />);

    expect(screen.queryByTestId("step-list")).not.toBeInTheDocument();
  });
});
