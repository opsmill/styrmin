/**
 * Steps on the deployment timeline (spec 019-task-steps, US1, FR-010, FR-019):
 * every entry expands to its steps and then its context diff, entries without
 * steps show a notice, and `delete_deployment` is labelled "Delete".
 */
import { describe, expect, it } from "vitest";
import { render, screen, userEvent, within } from "@/test/utils";
import {
  DeploymentTimeline,
  type TimelineEntry,
} from "@/components/deployment/DeploymentTimeline";
import type { StepListItem } from "@/components/deployment/StepList";

const STEPS: StepListItem[] = [
  {
    id: "s1",
    key: "plan",
    name: "Plan the changes",
    kind: "PLAN",
    status: "SUCCEEDED",
    startedAt: "2026-10-06T10:00:00+00:00",
    endedAt: "2026-10-06T10:00:02+00:00",
    durationSeconds: 2,
    attemptCount: 1,
    hasOutput: false,
  },
  {
    id: "s2",
    key: "resource:styrmindeployment",
    name: "Write the StyrminDeployment resource",
    kind: "RESOURCE_WRITE",
    status: "SUCCEEDED",
    startedAt: "2026-10-06T10:00:02+00:00",
    endedAt: "2026-10-06T10:00:03+00:00",
    durationSeconds: 1,
    attemptCount: 1,
    hasOutput: false,
  },
];

function makeEntry(
  overrides: Partial<TimelineEntry["task"]> = {},
  contextDiff: TimelineEntry["contextDiff"] = null,
): TimelineEntry {
  return {
    task: {
      id: "task-1",
      type: "upgrade_instance",
      status: "success",
      message: null,
      createdOn: "2026-10-06T10:00:00+00:00",
      updatedOn: "2026-10-06T10:00:30+00:00",
      startedByStepId: null,
      steps: STEPS,
      ...overrides,
    },
    applicationVersion: "1.2.0",
    contextDiff,
  };
}

function entryById(taskId: string): HTMLElement {
  const entry = screen
    .getAllByTestId("timeline-entry")
    .find((element) => element.getAttribute("data-task-id") === taskId);
  if (!entry) throw new Error(`no timeline entry for task ${taskId}`);
  return entry;
}

describe("DeploymentTimeline steps", () => {
  it("expands an entry to its steps, then its context diff", async () => {
    const user = userEvent.setup();
    await render(
      <DeploymentTimeline
        entries={[
          makeEntry(
            {},
            {
              changes: [
                {
                  path: "parameters.replicas",
                  action: "modified",
                  oldValue: 1,
                  newValue: 2,
                },
              ],
            },
          ),
        ]}
      />,
    );

    const entry = entryById("task-1");
    expect(entry).toHaveAttribute("data-expanded", "false");
    expect(within(entry).getByTestId("step-list")).not.toBeVisible();

    await user.click(within(entry).getByRole("button", { name: /Upgrade/ }));

    expect(entry).toHaveAttribute("data-expanded", "true");
    const stepList = within(entry).getByTestId("step-list");
    expect(stepList).toBeVisible();
    expect(
      within(stepList)
        .getAllByTestId("step-row")
        .map((row) => row.getAttribute("data-step-key")),
    ).toEqual(["plan", "resource:styrmindeployment"]);

    const diffPath = within(entry).getByText("parameters.replicas");
    expect(diffPath).toBeVisible();
    expect(
      stepList.compareDocumentPosition(diffPath) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("makes an entry without a context diff expandable", async () => {
    const user = userEvent.setup();
    await render(<DeploymentTimeline entries={[makeEntry()]} />);

    const entry = entryById("task-1");
    await user.click(within(entry).getByRole("button", { name: /Upgrade/ }));

    expect(within(entry).getByText("Plan the changes")).toBeVisible();
  });

  it("keeps the step rows of a collapsed entry in the page", async () => {
    await render(<DeploymentTimeline entries={[makeEntry()]} />);

    const rows = within(entryById("task-1")).getAllByTestId("step-row");
    expect(rows.map((row) => row.getAttribute("data-step-status"))).toEqual([
      "SUCCEEDED",
      "SUCCEEDED",
    ]);
  });

  it.each(["success", "failed"])(
    "shows the empty-steps notice for a finished task (%s)",
    async (status) => {
      const user = userEvent.setup();
      await render(
        <DeploymentTimeline entries={[makeEntry({ status, steps: [] })]} />,
      );

      const entry = entryById("task-1");
      await user.click(within(entry).getByRole("button", { name: /Upgrade/ }));

      expect(within(entry).getByTestId("steps-notice")).toHaveTextContent(
        "No steps recorded for this task.",
      );
      expect(within(entry).getByTestId("steps-notice")).toBeVisible();
      expect(within(entry).queryByTestId("step-list")).not.toBeInTheDocument();
    },
  );

  it.each(["pending", "running"])(
    "shows the waiting notice for an unfinished task (%s)",
    async (status) => {
      const user = userEvent.setup();
      await render(
        <DeploymentTimeline entries={[makeEntry({ status, steps: [] })]} />,
      );

      const entry = entryById("task-1");
      await user.click(within(entry).getByRole("button", { name: /Upgrade/ }));

      expect(within(entry).getByTestId("steps-notice")).toHaveTextContent(
        "Waiting for the first step.",
      );
    },
  );

  it('labels a delete_deployment task as "Delete"', async () => {
    await render(
      <DeploymentTimeline
        entries={[
          makeEntry({
            id: "task-delete",
            type: "delete_deployment",
            steps: [],
          }),
        ]}
      />,
    );

    const entry = entryById("task-delete");
    expect(entry).toHaveAttribute("data-task-type", "delete_deployment");
    expect(within(entry).getByText("Delete")).toBeInTheDocument();
    expect(
      within(entry).queryByText("delete_deployment"),
    ).not.toBeInTheDocument();
  });

  it("exposes the task that started an entry as a data attribute", async () => {
    await render(
      <DeploymentTimeline
        entries={[
          makeEntry({ type: "start_components", startedByStepId: "s9" }),
        ]}
      />,
    );

    expect(entryById("task-1")).toHaveAttribute(
      "data-started-by-step-id",
      "s9",
    );
  });
});
