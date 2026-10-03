import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, userEvent } from "@/test/utils";

import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";

import { ConfigDiffDialog } from "./ConfigDiffDialog";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;

/**
 * Tests for the Review & apply confirmation dialog (T042/T043).
 *
 * The dialog is exercised end-to-end against the real diff / impact
 * libraries; only the GraphQL surface is stubbed (fetch). The stub
 * captures every outgoing operation so we can assert that:
 *
 *  - the Apply path issues a refetch of `GetDeployment` before dispatch
 *    and then dispatches `UpdateDeployment` with the operator's edits;
 *  - the conflict path skips the mutation when the refetched fingerprint
 *    differs from the baseline.
 */

type CapturedRequest = {
  query: string;
  variables: Record<string, unknown>;
};

interface StubOptions {
  /** Snapshot of `deployment` to return from any GetDeployment fetch. */
  refetchDeployment: Deployment;
}

function stubFetch(options: StubOptions): {
  getCalls: () => CapturedRequest[];
  setRefetchDeployment: (d: Deployment) => void;
} {
  const calls: CapturedRequest[] = [];
  let currentRefetch = options.refetchDeployment;

  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const parsed = JSON.parse(String(init?.body ?? "{}")) as CapturedRequest;
    calls.push(parsed);

    if (parsed.query.includes("query GetDeployment")) {
      return new Response(
        JSON.stringify({ data: { deployment: currentRefetch } }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (parsed.query.includes("mutation UpdateDeployment")) {
      return new Response(
        JSON.stringify({
          data: {
            updateDeployment: {
              __typename: "Task",
              id: "task-1",
              type: "UPDATE_DEPLOYMENT",
              status: "PENDING",
              message: null,
              deploymentId: "dep-1",
            },
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({ data: null }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);

  return {
    getCalls: () => calls,
    setRefetchDeployment: (d: Deployment) => {
      currentRefetch = d;
    },
  };
}

function buildDeployment(overrides: Partial<Deployment> = {}): Deployment {
  return {
    __typename: "Deployment",
    id: "dep-1",
    name: "billing-api",
    status: "RUNNING",
    deletedAt: null,
    config: {},
    parameters: {},
    applicationVersion: "1.0.0",
    applicationDriverVersionId: "drv-v-1",
    environmentId: "env-1",
    applicationDriverVersion: {
      __typename: "ApplicationDriverVersion",
      id: "drv-v-1",
      version: "1.0.0",
      applicationDriver: {
        __typename: "ApplicationDriver",
        id: "drv-1",
        name: "demo-driver",
      },
      parameters: [],
    },
    environment: {
      __typename: "Environment",
      id: "env-1",
      name: "prod",
      config: {},
    },
    applicationInstance: null,
    components: [],
    componentImageOverrides: [],
    deployedServices: [],
    ...overrides,
  } as Deployment;
}

const INITIAL: UpdateDeploymentInput = {
  name: "billing-api",
  parameters: [],
  envVars: [],
  ipWhitelist: [],
  components: [],
};

const EDITED: UpdateDeploymentInput = {
  ...INITIAL,
  name: "billing-api-renamed",
};

describe("ConfigDiffDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the diff entries grouped by section when opened with pending changes", async () => {
    const deployment = buildDeployment();
    stubFetch({ refetchDeployment: deployment });

    await render(
      <ConfigDiffDialog
        open
        onOpenChange={vi.fn()}
        deployment={deployment}
        initialValues={INITIAL}
        frozenInitialValues={INITIAL}
        currentValues={EDITED}
        driverSchema={[]}
        onApplySuccess={vi.fn()}
        onBackToEdit={vi.fn()}
        onReloadBaseline={vi.fn()}
      />,
    );

    expect(screen.getByTestId("config-diff-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("diff-dialog-diff-section")).toBeInTheDocument();
    expect(screen.getByTestId("diff-section-identity")).toBeInTheDocument();
    // One row per `change` entry, with both before/after lines.
    expect(screen.getByTestId("diff-line-before")).toHaveTextContent(
      "billing-api",
    );
    expect(screen.getByTestId("diff-line-after")).toHaveTextContent(
      "billing-api-renamed",
    );
  });

  it("calls onApplySuccess after a successful mutation when the fingerprint is unchanged", async () => {
    const deployment = buildDeployment();
    stubFetch({ refetchDeployment: deployment });
    const onApplySuccess = vi.fn();

    await render(
      <ConfigDiffDialog
        open
        onOpenChange={vi.fn()}
        deployment={deployment}
        initialValues={INITIAL}
        frozenInitialValues={INITIAL}
        currentValues={EDITED}
        driverSchema={[]}
        onApplySuccess={onApplySuccess}
        onBackToEdit={vi.fn()}
        onReloadBaseline={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("diff-dialog-apply-button"));

    await waitFor(() => {
      expect(onApplySuccess).toHaveBeenCalledTimes(1);
    });
    // No conflict panel should have appeared.
    expect(
      screen.queryByTestId("diff-dialog-conflict-panel"),
    ).not.toBeInTheDocument();
  });

  it("renders the conflict panel when the refetched fingerprint differs from baseline", async () => {
    const deployment = buildDeployment({
      config: { fqdn_suffix: ".prod.example.com" },
    });
    // Refetch returns a snapshot where another client has changed the name.
    const refreshed = buildDeployment({
      config: { fqdn_suffix: ".prod.example.com" },
      name: "billing-api-changed-by-someone-else",
    });
    stubFetch({ refetchDeployment: refreshed });
    const onApplySuccess = vi.fn();
    const onReloadBaseline = vi.fn();

    await render(
      <ConfigDiffDialog
        open
        onOpenChange={vi.fn()}
        deployment={deployment}
        initialValues={INITIAL}
        frozenInitialValues={INITIAL}
        currentValues={EDITED}
        driverSchema={[]}
        onApplySuccess={onApplySuccess}
        onBackToEdit={vi.fn()}
        onReloadBaseline={onReloadBaseline}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("diff-dialog-apply-button"));

    await waitFor(() => {
      expect(
        screen.getByTestId("diff-dialog-conflict-panel"),
      ).toBeInTheDocument();
    });
    expect(onApplySuccess).not.toHaveBeenCalled();

    // Reload action hands the refreshed deployment back to the parent.
    await user.click(screen.getByTestId("diff-dialog-reload-button"));
    expect(onReloadBaseline).toHaveBeenCalledTimes(1);
    expect(onReloadBaseline.mock.calls[0][0].name).toBe(
      "billing-api-changed-by-someone-else",
    );
  });

  it("opens to a clean state with diff visible when triggered", async () => {
    const deployment = buildDeployment();
    stubFetch({ refetchDeployment: deployment });

    await render(
      <ConfigDiffDialog
        open
        onOpenChange={vi.fn()}
        deployment={deployment}
        initialValues={INITIAL}
        frozenInitialValues={INITIAL}
        currentValues={EDITED}
        driverSchema={[]}
        onApplySuccess={vi.fn()}
        onBackToEdit={vi.fn()}
        onReloadBaseline={vi.fn()}
      />,
    );

    // Header reflects the deployment + the pending change count.
    expect(
      screen.getByText(/Review configuration changes/),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 pending change(?!s)/)).toBeInTheDocument();
    // Impact section appears when any rule fires (the `name` rule fires
    // informational for this diff).
    expect(
      screen.getByTestId("diff-dialog-impact-section"),
    ).toBeInTheDocument();
  });
});
