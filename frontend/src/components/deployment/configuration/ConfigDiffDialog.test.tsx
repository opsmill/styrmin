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
      componentConfigs: [],
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
    componentContainerOverrides: [],
    componentReplicas: [],
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

  it("shows a cleared image override as a removal and submits image: null (018 US3)", async () => {
    const image = "registry.example/acme/simple-app-patched:0.1.0";
    const deployment = buildDeployment({
      config: { components: { server: { image } } },
    });
    const { getCalls } = stubFetch({ refetchDeployment: deployment });
    const initial: UpdateDeploymentInput = {
      ...INITIAL,
      components: [{ name: "server", envVars: [], image }],
    };
    const cleared: UpdateDeploymentInput = {
      ...INITIAL,
      components: [{ name: "server", envVars: [], image: "" }],
    };
    const onApplySuccess = vi.fn();

    await render(
      <ConfigDiffDialog
        open
        onOpenChange={vi.fn()}
        deployment={deployment}
        initialValues={initial}
        frozenInitialValues={initial}
        currentValues={cleared}
        driverSchema={[]}
        onApplySuccess={onApplySuccess}
        onBackToEdit={vi.fn()}
        onReloadBaseline={vi.fn()}
      />,
    );

    const rows = screen.getAllByTestId("diff-entry-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute("data-path", "components[server].image");
    expect(rows[0]).toHaveAttribute("data-kind", "remove");
    expect(screen.getByTestId("diff-line-before")).toHaveTextContent(image);
    expect(screen.queryByTestId("diff-line-after")).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("diff-dialog-apply-button"));

    await waitFor(() => expect(onApplySuccess).toHaveBeenCalledTimes(1));
    const mutation = getCalls().find((c) =>
      c.query.includes("mutation UpdateDeployment"),
    );
    expect(
      (mutation?.variables.input as UpdateDeploymentInput).components,
    ).toEqual([{ name: "server", envVars: [], image: null }]);
  });

  describe("service ingress overrides (#598, US3: T046)", () => {
    const TASK_MANAGER = {
      name: "task-manager",
      ingressClass: "tailscale",
      fqdnSuffix: "tailnet.example.ts.net",
    };
    const STORED_TASK_MANAGER = {
      "task-manager": {
        ingress_class: "tailscale",
        fqdn_suffix: "tailnet.example.ts.net",
      },
    };

    /** Open the dialog on `current`, press Apply, return the `input` of the mutation. */
    async function applyAndReadInput(
      deployment: Deployment,
      initial: UpdateDeploymentInput,
      current: UpdateDeploymentInput,
    ): Promise<UpdateDeploymentInput> {
      const { getCalls } = stubFetch({ refetchDeployment: deployment });
      const onApplySuccess = vi.fn();
      await render(
        <ConfigDiffDialog
          open
          onOpenChange={vi.fn()}
          deployment={deployment}
          initialValues={initial}
          frozenInitialValues={initial}
          currentValues={current}
          driverSchema={[]}
          onApplySuccess={onApplySuccess}
          onBackToEdit={vi.fn()}
          onReloadBaseline={vi.fn()}
        />,
      );
      // Apply is disabled while the diff has no change, so this fails first,
      // and says so, when `diff()` does not see `services`.
      expect(screen.getByTestId("diff-dialog-apply-button")).toBeEnabled();
      const user = userEvent.setup();
      await user.click(screen.getByTestId("diff-dialog-apply-button"));
      await waitFor(() => expect(onApplySuccess).toHaveBeenCalledTimes(1));
      const mutation = getCalls().find((c) =>
        c.query.includes("mutation UpdateDeployment"),
      );
      expect(mutation).toBeDefined();
      return mutation!.variables.input as UpdateDeploymentInput;
    }

    it("lists a new override in the diff and sends it as services in the update input", async () => {
      const deployment = buildDeployment();
      const current: UpdateDeploymentInput = {
        ...INITIAL,
        services: [TASK_MANAGER],
      };

      const input = await applyAndReadInput(deployment, INITIAL, current);

      expect(input.services).toEqual([TASK_MANAGER]);
    });

    it("shows the new override as one added row for the class and one for the suffix", async () => {
      const deployment = buildDeployment();
      stubFetch({ refetchDeployment: deployment });

      await render(
        <ConfigDiffDialog
          open
          onOpenChange={vi.fn()}
          deployment={deployment}
          initialValues={INITIAL}
          frozenInitialValues={INITIAL}
          currentValues={{ ...INITIAL, services: [TASK_MANAGER] }}
          driverSchema={[]}
          onApplySuccess={vi.fn()}
          onBackToEdit={vi.fn()}
          onReloadBaseline={vi.fn()}
        />,
      );

      const rows = screen.getAllByTestId("diff-entry-row");
      expect(rows.map((row) => row.getAttribute("data-path"))).toEqual([
        "services[task-manager].ingressClass",
        "services[task-manager].fqdnSuffix",
      ]);
      expect(rows.map((row) => row.getAttribute("data-kind"))).toEqual([
        "add",
        "add",
      ]);
    });

    it("omits an emptied field from the sent rows: the backend rejects an empty class or suffix", async () => {
      const deployment = buildDeployment({
        config: { services: STORED_TASK_MANAGER },
      });
      const initial: UpdateDeploymentInput = {
        ...INITIAL,
        services: [TASK_MANAGER],
      };
      const current: UpdateDeploymentInput = {
        ...INITIAL,
        services: [{ ...TASK_MANAGER, ingressClass: "" }],
      };

      const input = await applyAndReadInput(deployment, initial, current);

      expect(input.services).toEqual([
        { name: "task-manager", fqdnSuffix: "tailnet.example.ts.net" },
      ]);
      expect(input.services?.[0]).not.toHaveProperty("ingressClass");
    });

    it("sends no row for a service whose override the operator cleared", async () => {
      const deployment = buildDeployment({
        config: { services: STORED_TASK_MANAGER },
      });
      const initial: UpdateDeploymentInput = {
        ...INITIAL,
        services: [TASK_MANAGER],
      };

      const input = await applyAndReadInput(deployment, initial, {
        ...INITIAL,
        services: [],
      });

      // Full replacement: an empty list and an omitted field both clear it.
      expect(input.services ?? []).toEqual([]);
    });

    it("sends the stored overrides again when the operator edited another field", async () => {
      // `updateDeployment` replaces the whole stored config, so a save that
      // does not carry `services` clears every stored override (T030a). The
      // operator renames the deployment; the overrides must reach the mutation.
      const deployment = buildDeployment({
        config: { services: STORED_TASK_MANAGER },
      });
      const initial: UpdateDeploymentInput = {
        ...INITIAL,
        services: [TASK_MANAGER],
      };
      const current: UpdateDeploymentInput = {
        ...initial,
        name: "billing-api-renamed",
      };

      const input = await applyAndReadInput(deployment, initial, current);

      expect(input.name).toBe("billing-api-renamed");
      expect(input.services).toEqual([TASK_MANAGER]);
    });

    it("keeps an override stored by another client when the operator did not touch services", async () => {
      // The merge in `handleApply` takes an untouched field from the refreshed
      // deployment, so the stored `services` must survive `deploymentConfigToInput`.
      const deployment = buildDeployment({
        config: { services: STORED_TASK_MANAGER },
      });

      const input = await applyAndReadInput(deployment, INITIAL, EDITED);

      expect(input.name).toBe("billing-api-renamed");
      expect(input.services).toEqual([TASK_MANAGER]);
    });
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
