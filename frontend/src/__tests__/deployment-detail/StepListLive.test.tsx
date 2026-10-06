/**
 * Following a running task without reloading (spec 019-task-steps, US4,
 * FR-009): the "no report from the agent" notice, the entries that start
 * expanded, and step timings across the page's 10-second refreshes.
 * `rerender` stands in for a refresh that returns new data.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  DeploymentTimeline,
  type TimelineEntry,
} from "@/components/deployment/DeploymentTimeline";
import { StepList, type StepListItem } from "@/components/deployment/StepList";
import type { TaskResult } from "@/generated/graphql";

const LAST_REPORT = "2026-10-06T10:00:30+00:00";

function makeStep(overrides: Partial<StepListItem> = {}): StepListItem {
  return {
    id: "step-helmrelease",
    key: "operator:helmrelease",
    name: "Install or upgrade the HelmRelease",
    kind: "OPERATOR_PHASE",
    status: "RUNNING",
    startedAt: "2026-10-06T10:00:00+00:00",
    endedAt: null,
    durationSeconds: null,
    attemptCount: 1,
    hasOutput: false,
    noReportSince: null,
    ...overrides,
  };
}

function makeEntry(id: string, result: TaskResult): TimelineEntry {
  return {
    task: {
      id,
      type: "upgrade_instance",
      status: result === "RUNNING" ? "running" : "success",
      message: null,
      createdOn: "2026-10-06T10:00:00+00:00",
      updatedOn: "2026-10-06T10:00:30+00:00",
      result,
      startedByStepId: null,
      startedBy: null,
      startedTasks: [],
      steps: [makeStep({ id: `${id}-step` })],
    },
    applicationVersion: "1.2.0",
    contextDiff: null,
  };
}

function entryById(taskId: string): HTMLElement {
  const entry = screen
    .getAllByTestId("timeline-entry")
    .find((element) => element.getAttribute("data-task-id") === taskId);
  if (!entry) throw new Error(`no timeline entry for task ${taskId}`);
  return entry;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("StepList no-report notice", () => {
  it("shows the time of the last agent report on a running step", () => {
    render(<StepList steps={[makeStep({ noReportSince: LAST_REPORT })]} />);

    const row = screen.getByTestId("step-row");
    const notice = within(row).getByTestId("step-no-report");
    expect(notice).toHaveAttribute("data-no-report-since", LAST_REPORT);
    expect(notice).toHaveTextContent(
      `No report from the agent since ${new Date(LAST_REPORT).toLocaleString()}`,
    );
    // The step stays running: the notice only says the agent went quiet.
    expect(row).toHaveAttribute("data-step-status", "RUNNING");
    expect(within(row).getByTestId("step-status")).toHaveTextContent("Running");
  });

  it("shows no notice while the agent reports", () => {
    render(<StepList steps={[makeStep()]} />);

    expect(screen.queryByTestId("step-no-report")).not.toBeInTheDocument();
  });

  it("removes the notice when reports start again", () => {
    const { rerender } = render(
      <StepList steps={[makeStep({ noReportSince: LAST_REPORT })]} />,
    );
    expect(screen.getByTestId("step-no-report")).toBeInTheDocument();

    rerender(<StepList steps={[makeStep({ noReportSince: null })]} />);

    expect(screen.queryByTestId("step-no-report")).not.toBeInTheDocument();
  });
});

describe("DeploymentTimeline default expansion", () => {
  it("starts RUNNING and FAILED entries expanded", () => {
    render(
      <DeploymentTimeline
        entries={[
          makeEntry("task-running", "RUNNING"),
          makeEntry("task-failed", "FAILED"),
          makeEntry("task-succeeded", "SUCCEEDED"),
          makeEntry("task-superseded", "SUPERSEDED"),
        ]}
      />,
    );

    expect(entryById("task-running")).toHaveAttribute("data-expanded", "true");
    expect(entryById("task-failed")).toHaveAttribute("data-expanded", "true");
    expect(entryById("task-succeeded")).toHaveAttribute(
      "data-expanded",
      "false",
    );
    expect(entryById("task-superseded")).toHaveAttribute(
      "data-expanded",
      "false",
    );
    expect(
      within(entryById("task-running")).getByTestId("step-list"),
    ).toBeVisible();
  });

  it("starts a task that appears on a refresh expanded", () => {
    const old = makeEntry("task-old", "SUCCEEDED");
    const { rerender } = render(<DeploymentTimeline entries={[old]} />);

    rerender(
      <DeploymentTimeline entries={[makeEntry("task-new", "RUNNING"), old]} />,
    );

    expect(entryById("task-new")).toHaveAttribute("data-expanded", "true");
    expect(entryById("task-old")).toHaveAttribute("data-expanded", "false");
  });

  it("keeps an entry the user collapsed collapsed after a refresh", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <DeploymentTimeline entries={[makeEntry("task-1", "RUNNING")]} />,
    );

    await user.click(
      within(entryById("task-1")).getByTestId("timeline-entry-trigger"),
    );
    expect(entryById("task-1")).toHaveAttribute("data-expanded", "false");

    rerender(<DeploymentTimeline entries={[makeEntry("task-1", "RUNNING")]} />);

    expect(entryById("task-1")).toHaveAttribute("data-expanded", "false");
  });

  it("keeps a running entry expanded when it finishes", () => {
    const { rerender } = render(
      <DeploymentTimeline entries={[makeEntry("task-1", "RUNNING")]} />,
    );

    rerender(
      <DeploymentTimeline entries={[makeEntry("task-1", "SUCCEEDED")]} />,
    );

    expect(entryById("task-1")).toHaveAttribute(
      "data-task-result",
      "SUCCEEDED",
    );
    expect(entryById("task-1")).toHaveAttribute("data-expanded", "true");
  });
});

describe("StepList timings across refreshes", () => {
  it("updates the elapsed time of a running step, then shows its duration", () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-10-06T10:00:20+00:00"));
    const { rerender } = render(<StepList steps={[makeStep()]} />);
    expect(screen.getByTestId("step-duration")).toHaveTextContent(
      "running for 20s",
    );

    // The next refresh arrives 10 seconds later with the step still running.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    rerender(<StepList steps={[makeStep()]} />);
    expect(screen.getByTestId("step-duration")).toHaveTextContent(
      "running for 30s",
    );

    // The refresh after that has the step finished.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    rerender(
      <StepList
        steps={[
          makeStep({
            status: "SUCCEEDED",
            endedAt: "2026-10-06T10:00:35+00:00",
            durationSeconds: 35,
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("step-row")).toHaveAttribute(
      "data-step-status",
      "SUCCEEDED",
    );
    expect(screen.getByTestId("step-duration")).toHaveTextContent("35s");
    expect(screen.getByTestId("step-duration")).not.toHaveTextContent(
      "running for",
    );
  });
});
