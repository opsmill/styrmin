import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { SchedulingConfigDialog } from "./SchedulingConfigDialog";

/**
 * Integration tests for `SchedulingConfigDialog` against the typed
 * `UpdateDeploymentInput` GraphQL surface. The dialog rebuilds the input
 * from the read-side `Deployment.config` via `deploymentConfigToInput()`,
 * then overrides only the `scheduling` block. The two scenarios here
 * exercise the safety net that the full-replacement mutation does NOT
 * silently clear sibling config fields (envVars, ipWhitelist, components)
 * when the user submits a scheduling-only change.
 */

type CapturedRequest = {
  query: string;
  variables: Record<string, unknown>;
};

function stubFetchAndCapture(): {
  fetchMock: ReturnType<typeof vi.fn>;
  getCalls: () => CapturedRequest[];
} {
  const calls: CapturedRequest[] = [];
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const parsed = JSON.parse(String(init?.body ?? "{}")) as CapturedRequest;
    calls.push(parsed);
    return new Response(
      JSON.stringify({
        data: {
          updateDeployment: {
            __typename: "Task",
            id: "task-id-1",
            type: "UPDATE_DEPLOYMENT",
            status: "PENDING",
            message: null,
            deploymentId: "deployment-id-1",
          },
        },
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, getCalls: () => calls };
}

const PRE_EXISTING_CONFIG = {
  env_vars: { LOG_LEVEL: "info", PORT: "8080" },
  ip_whitelist: ["10.0.0.0/8"],
  components: {
    web: { env_vars: { COMPONENT_VAR: "x" } },
    worker: { env_vars: {} },
  },
  fqdn_suffix: ".prod.example.com",
  scheduling: { runtime_class: "kata-existing" },
};

async function findUpdateDeploymentCall(
  getCalls: () => CapturedRequest[],
): Promise<CapturedRequest> {
  // The query client also runs an `invalidateQueries({queryKey: ["GetDeployment"]})`
  // after the mutation resolves, but there's no GetDeployment query currently
  // observed by the QueryClient in the test, so the only fetch we expect is
  // the UpdateDeployment mutation itself.
  await waitFor(() => {
    expect(
      getCalls().find((c) => c.query.includes("mutation UpdateDeployment")),
    ).toBeDefined();
  });
  const call = getCalls().find((c) =>
    c.query.includes("mutation UpdateDeployment"),
  );
  if (!call) throw new Error("UpdateDeployment mutation never fired");
  return call;
}

describe("SchedulingConfigDialog (typed UpdateDeploymentInput)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("submits the typed input with all pre-existing config fields preserved plus the new scheduling block", async () => {
    const { getCalls } = stubFetchAndCapture();

    await render(
      <SchedulingConfigDialog
        open
        onOpenChange={vi.fn()}
        deploymentId="deployment-id-1"
        currentConfig={PRE_EXISTING_CONFIG}
      />,
    );

    // Edit the scheduling form: change the runtime class. This guarantees
    // the dialog's draft state differs from the initial extracted config
    // and the submitted scheduling block carries the new value.
    const runtimeInput = screen.getByLabelText("Runtime class name");
    await userEvent.clear(runtimeInput);
    await userEvent.type(runtimeInput, "kata-new");

    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    const call = await findUpdateDeploymentCall(getCalls);
    const variables = call.variables as {
      deploymentId: string;
      input: Record<string, unknown>;
    };

    expect(variables.deploymentId).toBe("deployment-id-1");

    // The pre-existing dict-shaped env_vars must arrive as a list of
    // {name, value} rows — both entries preserved verbatim.
    expect(variables.input.envVars).toEqual(
      expect.arrayContaining([
        { name: "LOG_LEVEL", value: "info" },
        { name: "PORT", value: "8080" },
      ]),
    );
    expect(variables.input.envVars).toHaveLength(2);

    // The pre-existing ipWhitelist passes through unchanged.
    expect(variables.input.ipWhitelist).toEqual(["10.0.0.0/8"]);

    // The pre-existing components dict must arrive as a list of
    // ComponentConfigInput rows; per-component env_vars must themselves be
    // translated to the list shape.
    expect(variables.input.components).toEqual(
      expect.arrayContaining([
        {
          name: "web",
          envVars: [{ name: "COMPONENT_VAR", value: "x" }],
        },
        { name: "worker", envVars: [] },
      ]),
    );
    expect(variables.input.components).toHaveLength(2);

    // Pass-through scalar fields survive the round-trip.
    expect(variables.input.fqdnSuffix).toBe(".prod.example.com");

    // The new scheduling block from the dialog overrides the persisted one.
    expect(variables.input.scheduling).toEqual({ runtimeClass: "kata-new" });
  });

  it("does NOT clear envVars, ipWhitelist, or components when only scheduling is edited (full-replacement footgun regression)", async () => {
    // This is the explicit no-regression test called out in plan.md
    // "Frontend Testing Scope". Before the dialog was rewired to call
    // `deploymentConfigToInput()`, submitting a scheduling change against
    // the new full-replacement input would have sent only the scheduling
    // block — leaving every other top-level field as undefined and silently
    // wiping the persisted envVars, ipWhitelist, and components dicts.
    const { getCalls } = stubFetchAndCapture();

    await render(
      <SchedulingConfigDialog
        open
        onOpenChange={vi.fn()}
        deploymentId="deployment-id-1"
        currentConfig={PRE_EXISTING_CONFIG}
      />,
    );

    // Submit without touching the form. The dialog still rebuilds the
    // input from `currentConfig` and dispatches the mutation.
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    const call = await findUpdateDeploymentCall(getCalls);
    const input = (call.variables as { input: Record<string, unknown> }).input;

    // Each of these would be `undefined` or `[]` under the regression we
    // are guarding against. Assert they are present and non-empty.
    expect(input.envVars).toBeDefined();
    expect(input.envVars).not.toEqual([]);
    expect((input.envVars as unknown[]).length).toBe(2);

    expect(input.ipWhitelist).toBeDefined();
    expect(input.ipWhitelist).not.toEqual([]);
    expect(input.ipWhitelist).toEqual(["10.0.0.0/8"]);

    expect(input.components).toBeDefined();
    expect(input.components).not.toEqual([]);
    expect((input.components as unknown[]).length).toBe(2);
  });
});
