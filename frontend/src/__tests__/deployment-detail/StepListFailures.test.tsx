/**
 * How each SC-001 failure type looks in the StepList (spec 019-task-steps,
 * US2): the error of each attempt, FluxCD's detail, the rollback line and the
 * command output loaded on "Show output".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, userEvent, waitFor, within } from "@/test/utils";
import { StepList, type StepListItem } from "@/components/deployment/StepList";

const STEP_ID = "5b0f3c1e-1d2a-4c55-9e0b-6f7a8b9c0d1e";

function makeStep(overrides: Partial<StepListItem> = {}): StepListItem {
  return {
    id: STEP_ID,
    key: "hook:upgrade:core",
    name: "Run the upgrade action",
    kind: "HOOK",
    status: "FAILED",
    startedAt: "2026-10-06T10:00:00+00:00",
    endedAt: "2026-10-06T10:00:12+00:00",
    durationSeconds: 12,
    attemptCount: 1,
    errors: [],
    detail: null,
    rolledBackAt: null,
    rollbackMessage: null,
    hasOutput: false,
    outputTruncated: false,
    ...overrides,
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StepList failure causes", () => {
  it("shows the error of a failed hook step", async () => {
    await render(
      <StepList
        steps={[
          makeStep({
            errors: [
              {
                attempt: 1,
                message: "RuntimeError: target version 0.9.0-raise refused",
                occurredAt: "2026-10-06T10:00:12+00:00",
              },
            ],
          }),
        ]}
      />,
    );

    const row = screen.getByTestId("step-row");
    expect(row).toHaveAttribute("data-step-status", "FAILED");
    const [error] = within(row).getAllByTestId("step-error");
    expect(error).toHaveAttribute("data-attempt", "1");
    expect(error).toHaveAttribute(
      "data-occurred-at",
      "2026-10-06T10:00:12+00:00",
    );
    expect(error).toHaveTextContent(
      `Attempt 1 failed at ${new Date("2026-10-06T10:00:12+00:00").toLocaleString()}`,
    );
    expect(within(error).getByTestId("step-error-message")).toHaveTextContent(
      "RuntimeError: target version 0.9.0-raise refused",
    );
    expect(within(row).queryByTestId("show-output")).not.toBeInTheDocument();
  });

  it("loads the output of a failed hook step only on Show output", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: {
          step: {
            id: STEP_ID,
            output: "step-output-1\nstep-output-2\n",
            outputTruncated: true,
          },
        },
      }),
    );

    await render(
      <StepList
        steps={[
          makeStep({
            errors: [
              {
                attempt: 1,
                message: "Job my-app-migrate failed",
                occurredAt: "2026-10-06T10:00:12+00:00",
              },
            ],
            hasOutput: true,
            outputTruncated: true,
          }),
        ]}
      />,
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId("step-output")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show output" }));

    const output = await screen.findByTestId("step-output");
    expect(output.tagName).toBe("PRE");
    expect(output.textContent).toBe("step-output-1\nstep-output-2\n");
    expect(screen.getByTestId("output-truncated")).toHaveTextContent(
      "Earlier output was cut",
    );
    expect(screen.getByTestId("show-output")).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const body = JSON.parse(String(fetchMock.mock.calls[0]![1]!.body)) as {
      query: string;
      variables: Record<string, unknown>;
    };
    expect(body.query).toContain("query GetStepOutput");
    expect(body.variables).toEqual({ stepId: STEP_ID });

    await user.click(screen.getByRole("button", { name: "Hide output" }));
    expect(screen.queryByTestId("step-output")).not.toBeInTheDocument();
  });

  it("shows no cut notice when the whole output was kept", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: {
          step: { id: STEP_ID, output: "done\n", outputTruncated: false },
        },
      }),
    );

    await render(<StepList steps={[makeStep({ hasOutput: true })]} />);
    await user.click(screen.getByRole("button", { name: "Show output" }));

    await waitFor(() =>
      expect(screen.getByTestId("step-output").textContent).toBe("done\n"),
    );
    expect(screen.queryByTestId("output-truncated")).not.toBeInTheDocument();
  });

  it("shows FluxCD's detail and the pod reasons of a failed HelmRelease step", async () => {
    const message =
      "HelmRelease my-app is not ready: Helm upgrade failed: context deadline exceeded\n" +
      "Pods not ready: my-app-6d9 (app: ImagePullBackOff); my-app-7f1 (app: ErrImagePull)";
    await render(
      <StepList
        steps={[
          makeStep({
            key: "operator:helmrelease",
            name: "Install or upgrade the HelmRelease",
            kind: "OPERATOR_PHASE",
            errors: [
              {
                attempt: 1,
                message,
                occurredAt: "2026-10-06T10:07:00+00:00",
              },
            ],
            detail:
              "UpgradeFailed: Helm upgrade failed for release styrmin/my-app: context deadline exceeded",
          }),
        ]}
      />,
    );

    const row = screen.getByTestId("step-row");
    expect(row).toHaveAttribute("data-step-key", "operator:helmrelease");
    const errorMessage = within(row).getByTestId("step-error-message");
    // Pod reasons follow a line break, which the block keeps.
    expect(errorMessage.textContent).toBe(message);
    expect(errorMessage).toHaveClass("whitespace-pre-wrap");
    expect(within(row).getByTestId("step-detail")).toHaveTextContent(
      "UpgradeFailed: Helm upgrade failed for release styrmin/my-app: context deadline exceeded",
    );
    expect(row).toHaveTextContent("ImagePullBackOff");
  });

  it("shows the error of each attempt of a failed prerequisites step, newest first", async () => {
    await render(
      <StepList
        steps={[
          makeStep({
            key: "operator:prerequisites",
            name: "Create network policies and secrets",
            kind: "OPERATOR_PHASE",
            attemptCount: 3,
            errors: [1, 2, 3].map((attempt) => ({
              attempt,
              message: `networkpolicies "allow-ingress" is forbidden: exceeded quota (attempt ${attempt})`,
              occurredAt: `2026-10-06T10:0${attempt}:00+00:00`,
            })),
          }),
        ]}
      />,
    );

    const row = screen.getByTestId("step-row");
    expect(within(row).getByTestId("step-attempts")).toHaveTextContent(
      "3 attempts",
    );
    const errors = within(row).getAllByTestId("step-error");
    expect(errors.map((error) => error.getAttribute("data-attempt"))).toEqual([
      "3",
      "2",
      "1",
    ]);
    expect(
      errors.map(
        (error) => within(error).getByTestId("step-error-message").textContent,
      ),
    ).toEqual([
      'networkpolicies "allow-ingress" is forbidden: exceeded quota (attempt 3)',
      'networkpolicies "allow-ingress" is forbidden: exceeded quota (attempt 2)',
      'networkpolicies "allow-ingress" is forbidden: exceeded quota (attempt 1)',
    ]);
  });

  it("says when FluxCD rolled back the release and why", async () => {
    const rolledBackAt = "2026-10-06T10:05:30+00:00";
    await render(
      <StepList
        steps={[
          makeStep({
            key: "operator:helmrelease",
            name: "Install or upgrade the HelmRelease",
            kind: "OPERATOR_PHASE",
            rolledBackAt,
            rollbackMessage:
              "Helm rollback to previous release styrmin/my-app.v3",
          }),
        ]}
      />,
    );

    const rollback = screen.getByTestId("step-rollback");
    expect(rollback).toHaveAttribute("data-rolled-back-at", rolledBackAt);
    expect(rollback).toHaveTextContent(
      `FluxCD rolled back the release at ${new Date(rolledBackAt).toLocaleString()}: Helm rollback to previous release styrmin/my-app.v3`,
    );
  });

  it("shows no failure details for a step without errors, detail or output", async () => {
    await render(<StepList steps={[makeStep({ status: "SUCCEEDED" })]} />);

    expect(screen.queryByTestId("step-errors")).not.toBeInTheDocument();
    expect(screen.queryByTestId("step-detail")).not.toBeInTheDocument();
    expect(screen.queryByTestId("step-rollback")).not.toBeInTheDocument();
    expect(screen.queryByTestId("show-output")).not.toBeInTheDocument();
  });
});
