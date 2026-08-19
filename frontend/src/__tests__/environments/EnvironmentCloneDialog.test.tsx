/**
 * CloneEnvironmentDialog tests (010-environment-clone, US1–US4 / FR-012).
 *
 * The dialog is the only place in the frontend that authors a
 * `cloneEnvironment` request, and three of its input contracts are silently
 * destructive if they drift:
 *
 * - `deploymentIds` **omitted** means "all eligible"; `[]` means "configuration
 *   only". Sending the array as a stand-in for "no filter" would quietly turn
 *   every default clone into an empty one, so both branches are asserted on the
 *   exact mutation variables.
 * - `configOverride` carries only the keys the operator typed. An explicit
 *   `null` on an untouched field would wipe the captured value.
 * - `clearConfigFields` names snake_case `EnvironmentConfig` fields taken from
 *   the source environment's own config.
 *
 * Role gating is asserted rather than assumed: cloning is ADMIN-only (FR-010).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { render, screen, userEvent, waitFor, within } from "@/test/utils";
import type { AuthContextValue } from "@/auth/AuthProvider";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import {
  CloneEnvironmentDialog,
  clearableConfigFields,
  cloneIneligibilityReason,
  describeCloneMutationError,
  parseConfigOverride,
  unknownOverrideFields,
  type CloneCandidateDeployment,
} from "@/components/environment/CloneEnvironmentDialog";

const cloneMutateAsync = vi.fn();
const useCloneEnvironmentMutation = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useCloneEnvironmentMutation: (...args: unknown[]) =>
      useCloneEnvironmentMutation(...args),
  };
});

const ENVIRONMENT_ID = "env-1";

function deployment(
  overrides: Partial<CloneCandidateDeployment> & { name: string },
): CloneCandidateDeployment {
  return {
    id: `dep-${overrides.name}`,
    internal: false,
    deletedAt: null,
    applicationInstance: { id: `inst-${overrides.name}` },
    ...overrides,
  };
}

/** Two eligible apps plus one of each ineligibility flavour. */
const DEPLOYMENTS: CloneCandidateDeployment[] = [
  deployment({ name: "api" }),
  deployment({ name: "worker" }),
  deployment({ name: "styrmin-agent", internal: true }),
  deployment({ name: "never-deployed", applicationInstance: null }),
  deployment({ name: "old", deletedAt: "2026-08-01T00:00:00Z" }),
];

const CONFIG: Record<string, unknown> = {
  ingress_class: "nginx",
  fqdn_suffix: "example.com",
  // Unset fields are not clearable candidates — clearing them is a no-op with
  // nothing to show for it.
  db_size: null,
};

function authFor(role: "READ_ONLY" | "READ_WRITE" | "ADMIN"): AuthContextValue {
  return {
    currentUser: {
      id: `u-${role}`,
      username: role.toLowerCase(),
      displayName: role,
      role,
      effectiveRole: role,
      active: true,
    },
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

async function openDialog(
  options: {
    deployments?: CloneCandidateDeployment[];
    config?: Record<string, unknown> | null;
  } = {},
) {
  await render(
    <CloneEnvironmentDialog
      environmentId={ENVIRONMENT_ID}
      environmentName="prod"
      deployments={options.deployments ?? DEPLOYMENTS}
      config={options.config === undefined ? CONFIG : options.config}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByTestId("clone-environment-button"));
  expect(await screen.findByTestId("clone-environment-dialog")).toBeVisible();
  return user;
}

/**
 * Put text into a field by pasting rather than typing.
 *
 * `userEvent.type` reads `{` and `}` as keyboard descriptors, so JSON typed
 * character by character throws before it reaches the field.
 */
async function pasteInto(
  user: ReturnType<typeof userEvent.setup>,
  element: HTMLElement,
  text: string,
) {
  await user.click(element);
  await user.paste(text);
}

/** The single set of variables the mutation was called with. */
function submittedVariables(): Record<string, unknown> {
  expect(cloneMutateAsync).toHaveBeenCalledTimes(1);
  return cloneMutateAsync.mock.calls[0]![0] as Record<string, unknown>;
}

describe("clone eligibility helpers", () => {
  it("mirrors the environment-backup eligibility rule", () => {
    expect(cloneIneligibilityReason(deployment({ name: "api" }))).toBeNull();
    expect(
      cloneIneligibilityReason(deployment({ name: "a", internal: true })),
    ).toBe("internal");
    expect(
      cloneIneligibilityReason(
        deployment({ name: "a", applicationInstance: null }),
      ),
    ).toBe("no_active_instance");
    expect(
      cloneIneligibilityReason(
        deployment({ name: "a", deletedAt: "2026-01-01T00:00:00Z" }),
      ),
    ).toBe("tombstoned");
  });

  it("reports a deleted internal deployment as deleted", () => {
    // Both flags are true; the deletion is the half the operator can act on.
    expect(
      cloneIneligibilityReason(
        deployment({
          name: "a",
          internal: true,
          deletedAt: "2026-01-01T00:00:00Z",
        }),
      ),
    ).toBe("tombstoned");
  });
});

describe("parseConfigOverride", () => {
  it("treats blank as no override rather than as an error", () => {
    // Omitting the argument and sending `{}` are different statements; blank
    // has to resolve to the former.
    expect(parseConfigOverride("   \n ")).toEqual({ value: null, error: null });
  });

  it("rejects malformed JSON with a readable reason", () => {
    const result = parseConfigOverride("{ not json");
    expect(result.value).toBeNull();
    expect(result.error).toMatch(/not valid json/i);
  });

  it("rejects a JSON value that is not an object", () => {
    expect(parseConfigOverride("[1, 2]").error).toMatch(
      /must be a JSON object/,
    );
    expect(parseConfigOverride('"nginx"').error).toMatch(
      /must be a JSON object/,
    );
    expect(parseConfigOverride("null").error).toMatch(/must be a JSON object/);
  });

  it("accepts an UpdateEnvironmentInput object", () => {
    expect(
      parseConfigOverride('{"envVars": [{"name": "A", "value": "b"}]}'),
    ).toEqual({
      value: { envVars: [{ name: "A", value: "b" }] },
      error: null,
    });
  });
});

describe("unknownOverrideFields", () => {
  it("flags the CLI's snake_case spelling, which this boundary rejects", () => {
    // The CLI validates through the SDK's Pydantic aliases and accepts
    // `env_vars`; GraphQL accepts `envVars` only.
    expect(unknownOverrideFields({ env_vars: [] })).toEqual(["env_vars"]);
  });

  it("passes a fully camelCase override", () => {
    expect(
      unknownOverrideFields({ envVars: [], ingressClass: "nginx" }),
    ).toEqual([]);
  });
});

describe("clearableConfigFields", () => {
  it("offers the set fields, snake_case, sorted, dropping unset ones", () => {
    expect(clearableConfigFields(CONFIG)).toEqual([
      "fqdn_suffix",
      "ingress_class",
    ]);
  });

  it("returns nothing for an absent config", () => {
    expect(clearableConfigFields(null)).toEqual([]);
    expect(clearableConfigFields({})).toEqual([]);
  });
});

describe("describeCloneMutationError", () => {
  it("keys on the typed code, never on the message text", () => {
    expect(
      describeCloneMutationError(
        new GraphQLOperationError(
          "ALREADY_EXISTS",
          "environment prod-x exists",
        ),
      ),
    ).toMatch(/name is already taken/i);
    expect(
      describeCloneMutationError(
        new GraphQLOperationError("ALREADY_IN_PROGRESS", "busy"),
      ),
    ).toMatch(/another environment-level operation/i);
    expect(
      describeCloneMutationError(
        new GraphQLOperationError("NOT_FOUND", "deployment_ids=[…]"),
      ),
    ).toMatch(/no longer exists/i);
    expect(
      describeCloneMutationError(
        new GraphQLOperationError("VALIDATION_ERROR", "unknown field nope"),
      ),
    ).toMatch(/rejected as invalid/i);
    expect(
      describeCloneMutationError(
        new GraphQLOperationError("FORBIDDEN", "admin required"),
      ),
    ).toMatch(/ADMIN role/);
  });

  it("keeps the server's own message so the specifics survive", () => {
    expect(
      describeCloneMutationError(
        new GraphQLOperationError("ALREADY_EXISTS", "prod-rehearsal is taken"),
      ),
    ).toContain("prod-rehearsal is taken");
  });

  it("falls back to a plain error message", () => {
    expect(describeCloneMutationError(new Error("network down"))).toBe(
      "network down",
    );
  });
});

describe("CloneEnvironmentDialog", () => {
  beforeEach(() => {
    cloneMutateAsync.mockReset();
    cloneMutateAsync.mockResolvedValue({
      cloneEnvironment: {
        id: "clone-1",
        name: "prod-rehearsal",
        // A clone can come back already IN_PROGRESS: an upfront skip counts as
        // recorded progress, so PENDING is not a guaranteed first status.
        status: "IN_PROGRESS",
        createdOn: "2026-08-19T10:00:00Z",
      },
    });
    useCloneEnvironmentMutation.mockReset();
    // The stub honours the component's `onSuccess` so the guideline-mandated
    // invalidation is reachable from a test.
    useCloneEnvironmentMutation.mockImplementation(
      (options?: { onSuccess?: (data: unknown) => void }) => ({
        mutateAsync: async (variables: unknown) => {
          const data = await cloneMutateAsync(variables);
          options?.onSuccess?.(data);
          return data;
        },
        isPending: false,
      }),
    );
  });

  it("hides the whole surface from a non-ADMIN operator", async () => {
    // FR-010: cloning creates an environment and reads every included
    // deployment's data. READ_WRITE is not enough, and the trigger is absent
    // rather than merely disabled.
    for (const role of ["READ_ONLY", "READ_WRITE"] as const) {
      const view = await render(
        <CloneEnvironmentDialog
          environmentId={ENVIRONMENT_ID}
          environmentName="prod"
          deployments={DEPLOYMENTS}
          config={CONFIG}
        />,
        { auth: authFor(role) },
      );
      expect(
        screen.queryByTestId("clone-environment-button"),
      ).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("offers the clone action to an ADMIN operator", async () => {
    await render(
      <CloneEnvironmentDialog
        environmentId={ENVIRONMENT_ID}
        environmentName="prod"
        deployments={DEPLOYMENTS}
        config={CONFIG}
      />,
      { auth: authFor("ADMIN") },
    );
    expect(screen.getByTestId("clone-environment-button")).toBeInTheDocument();
  });

  it("offers eligible applications and locks ineligible ones with a reason", async () => {
    const user = await openDialog();

    const rows = screen.getAllByTestId("clone-deployment-option");
    expect(rows).toHaveLength(5);

    const byName = new Map(
      rows.map((row) => [row.getAttribute("data-deployment-name"), row]),
    );

    for (const name of ["api", "worker"]) {
      const row = byName.get(name)!;
      expect(row).toHaveAttribute("data-eligible", "true");
      expect(row).toHaveAttribute("data-ineligible-reason", "");
    }

    // Every ineligible deployment is present-but-locked, with an attributed
    // reason: one silently missing from the picker is indistinguishable from
    // one that was never in the environment.
    for (const [name, reason, label] of [
      ["styrmin-agent", "internal", "internal"],
      ["never-deployed", "no_active_instance", "never deployed"],
      ["old", "tombstoned", "deleted"],
    ] as const) {
      const row = byName.get(name)!;
      expect(row).toHaveAttribute("data-eligible", "false");
      expect(row).toHaveAttribute("data-ineligible-reason", reason);
      expect(row).toHaveTextContent(label);
      // Base UI renders the disabled state as `aria-disabled` on a
      // `role="checkbox"` element, not as the native `disabled` attribute — so
      // the lock is asserted both on the ARIA state and behaviourally.
      const checkbox = within(row).getByTestId("clone-deployment-checkbox");
      expect(checkbox).toHaveAttribute("aria-disabled", "true");
      await user.click(checkbox);
      expect(row).toHaveAttribute("data-selected", "false");
    }
  });

  it("refuses to submit without a target name", async () => {
    const user = await openDialog();

    await user.click(screen.getByTestId("clone-submit-button"));

    expect(
      await screen.findByTestId("clone-environment-name-error"),
    ).toHaveTextContent(/name is required/i);
    expect(cloneMutateAsync).not.toHaveBeenCalled();
  });

  it("treats a whitespace-only name as absent", async () => {
    const user = await openDialog();

    await user.type(screen.getByTestId("clone-environment-name-input"), "   ");
    await user.click(screen.getByTestId("clone-submit-button"));

    expect(
      await screen.findByTestId("clone-environment-name-error"),
    ).toBeInTheDocument();
    expect(cloneMutateAsync).not.toHaveBeenCalled();
  });

  it("omits deploymentIds entirely when every eligible application is included", async () => {
    // The load-bearing case: `null`/omitted means "all eligible" (FR-003) while
    // `[]` means "configuration only". Sending `[]` here would turn the default
    // clone into an empty one.
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "prod-rehearsal",
    );
    await user.click(screen.getByTestId("clone-submit-button"));

    await waitFor(() => expect(cloneMutateAsync).toHaveBeenCalled());
    const variables = submittedVariables();
    expect(variables).toEqual({
      environmentId: ENVIRONMENT_ID,
      name: "prod-rehearsal",
    });
    expect("deploymentIds" in variables).toBe(false);
  });

  it("sends the explicit selection when the operator picks a subset", async () => {
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "prod-rehearsal",
    );
    // Hand the selection over, then drop one eligible application (US2).
    await user.click(screen.getByTestId("clone-include-all-checkbox"));
    const worker = screen
      .getAllByTestId("clone-deployment-option")
      .find((row) => row.getAttribute("data-deployment-name") === "worker")!;
    await user.click(within(worker).getByTestId("clone-deployment-checkbox"));

    await user.click(screen.getByTestId("clone-submit-button"));

    await waitFor(() => expect(cloneMutateAsync).toHaveBeenCalled());
    expect(submittedVariables().deploymentIds).toEqual(["dep-api"]);
  });

  it("sends an explicit empty selection as a configuration-only clone", async () => {
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "config-only",
    );
    await user.click(screen.getByTestId("clone-include-all-checkbox"));
    for (const name of ["api", "worker"]) {
      const row = screen
        .getAllByTestId("clone-deployment-option")
        .find(
          (candidate) =>
            candidate.getAttribute("data-deployment-name") === name,
        )!;
      await user.click(within(row).getByTestId("clone-deployment-checkbox"));
    }

    expect(screen.getByTestId("clone-no-selection-note")).toBeInTheDocument();
    await user.click(screen.getByTestId("clone-submit-button"));

    await waitFor(() => expect(cloneMutateAsync).toHaveBeenCalled());
    // `[]`, not omitted: an empty selection is a legal request for a clone of
    // the environment configuration alone.
    expect(submittedVariables().deploymentIds).toEqual([]);
  });

  it("sends the override and the cleared fields, and omits both when untouched", async () => {
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "prod-rehearsal",
    );
    await pasteInto(
      user,
      screen.getByTestId("clone-config-override-input"),
      '{"envVars": [{"name": "SMTP_HOST", "value": "sink.local"}]}',
    );
    const ingress = screen
      .getAllByTestId("clone-clear-field-option")
      .find(
        (row) => row.getAttribute("data-config-field") === "ingress_class",
      )!;
    await user.click(within(ingress).getByTestId("clone-clear-field-checkbox"));

    await user.click(screen.getByTestId("clone-submit-button"));

    await waitFor(() => expect(cloneMutateAsync).toHaveBeenCalled());
    const variables = submittedVariables();
    // Only the key the operator typed: a present field replaces the captured
    // one wholesale, so padding the input with nulls would wipe the rest.
    expect(variables.configOverride).toEqual({
      envVars: [{ name: "SMTP_HOST", value: "sink.local" }],
    });
    expect(variables.clearConfigFields).toEqual(["ingress_class"]);
  });

  it("blocks submission on an unparseable override", async () => {
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "prod-rehearsal",
    );
    await pasteInto(
      user,
      screen.getByTestId("clone-config-override-input"),
      "{ nope",
    );

    expect(screen.getByTestId("clone-config-override-error")).toHaveTextContent(
      /not valid json/i,
    );
    expect(screen.getByTestId("clone-submit-button")).toBeDisabled();
    expect(cloneMutateAsync).not.toHaveBeenCalled();
  });

  it("warns about a snake_case override key without blocking it", async () => {
    // The CLI accepts `env_vars`; this boundary does not. The warning is
    // non-blocking so a field the frontend has not heard of yet still gets
    // through to the backend, which is the authority.
    const user = await openDialog();

    await pasteInto(
      user,
      screen.getByTestId("clone-config-override-input"),
      '{"env_vars": []}',
    );

    expect(
      screen.getByTestId("clone-config-override-warning"),
    ).toHaveTextContent(/env_vars/);
    expect(screen.getByTestId("clone-submit-button")).not.toBeDisabled();
  });

  it("says so when the environment has no configuration to clear", async () => {
    await openDialog({ config: null });
    expect(screen.getByTestId("clone-clear-fields-empty")).toHaveTextContent(
      /nothing to clear/i,
    );
  });

  it("says so when the environment has no applications to pick", async () => {
    await openDialog({ deployments: [] });
    expect(
      screen.getByTestId("clone-deployment-picker-empty"),
    ).toHaveTextContent(/configuration only/i);
  });

  it("invalidates the clones list, the snapshot list and the environment list", async () => {
    // A clone writes to three places the rest of the UI reads: its own record
    // list, the fresh capture on the Backups tab, and the environment listing.
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "prod-rehearsal",
    );
    await user.click(screen.getByTestId("clone-submit-button"));

    await waitFor(() => expect(cloneMutateAsync).toHaveBeenCalled());
    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    for (const key of [
      ["ListEnvironmentClones"],
      ["ListEnvironmentBackups"],
      ["ListEnvironments"],
    ]) {
      expect(keys).toContainEqual(key);
    }
    invalidate.mockRestore();
  });

  it("closes on a successful clone", async () => {
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "prod-rehearsal",
    );
    await user.click(screen.getByTestId("clone-submit-button"));

    await waitFor(() =>
      expect(
        screen.queryByTestId("clone-environment-dialog"),
      ).not.toBeInTheDocument(),
    );
  });

  it("surfaces a taken name inline and stays open so it can be changed", async () => {
    cloneMutateAsync.mockRejectedValue(
      new GraphQLOperationError(
        "ALREADY_EXISTS",
        "environment 'prod-rehearsal' already exists",
      ),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = await openDialog();

    await user.type(
      screen.getByTestId("clone-environment-name-input"),
      "prod-rehearsal",
    );
    await user.click(screen.getByTestId("clone-submit-button"));

    expect(
      await screen.findByTestId("clone-environment-error"),
    ).toHaveTextContent(/name is already taken/i);
    expect(screen.getByTestId("clone-environment-dialog")).toBeVisible();
    expect(screen.getByTestId("clone-environment-name-input")).toHaveValue(
      "prod-rehearsal",
    );
  });

  it("surfaces a busy source environment inline", async () => {
    cloneMutateAsync.mockRejectedValue(
      new GraphQLOperationError(
        "ALREADY_IN_PROGRESS",
        "an environment backup is already in progress",
      ),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = await openDialog();

    await user.type(screen.getByTestId("clone-environment-name-input"), "x");
    await user.click(screen.getByTestId("clone-submit-button"));

    expect(
      await screen.findByTestId("clone-environment-error"),
    ).toHaveTextContent(/another environment-level operation/i);
  });
});
