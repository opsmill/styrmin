/**
 * Create-time backup retention on the New Environment dialog
 * (016-backup-retention-ttl).
 *
 * An environment could only be given a retention policy *after* creation, via
 * the Configuration tab — so every environment spent its first moments on the
 * cluster's policy, and an operator provisioning one with a deliberate
 * retention had to remember a second, separate step.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ThemeProvider } from "@/hooks/use-theme";
import { CreateEnvironmentDialog } from "@/pages/environments/CreateEnvironmentDialog";
import { MAX_BACKUP_TTL_HOURS } from "@/lib/backup-ttl";

const createEnvironmentMutateAsync = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useListClustersQuery: () => ({
      data: { clusters: [{ id: "cluster-1", name: "kind" }] },
      isLoading: false,
      error: null,
    }),
    useCreateEnvironmentMutation: () => ({
      mutateAsync: createEnvironmentMutateAsync,
      isPending: false,
    }),
  };
});

/** Open the dialog and expand Advanced Configuration. */
async function openAdvancedForm() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  await act(async () => {
    render(
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <CreateEnvironmentDialog onCreated={() => {}} />
        </QueryClientProvider>
      </ThemeProvider>,
    );
  });

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /New Environment/i }));
  await user.click(
    screen.getByRole("button", { name: /Advanced Configuration/i }),
  );
  return user;
}

/**
 * Fill the required top-level fields (name + cluster) and submit.
 *
 * Both are driven through the real UI so a submit that reaches the mutation
 * proves the whole form validated, not just the retention field.
 */
async function fillRequiredAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Name"), "production");
  // The cluster Select renders as a combobox; pick the single option.
  await user.click(screen.getByRole("combobox"));
  await user.click(await screen.findByRole("option", { name: "kind" }));
  await user.click(screen.getByRole("button", { name: /^Create$/i }));
}

/** The `config` payload the mutation was called with. */
function submittedConfig(): Record<string, unknown> | null {
  expect(createEnvironmentMutateAsync).toHaveBeenCalled();
  const [args] = createEnvironmentMutateAsync.mock.calls.at(-1)!;
  return (args as { config: Record<string, unknown> | null }).config;
}

describe("CreateEnvironmentDialog: backup retention TTL", () => {
  beforeEach(() => {
    createEnvironmentMutateAsync.mockReset();
    createEnvironmentMutateAsync.mockResolvedValue({
      createEnvironment: { id: "env-1", name: "production" },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exposes the field in Advanced Configuration with the documented id", async () => {
    await openAdvancedForm();

    const input = screen.getByLabelText("Backup Retention TTL");
    // The id is the selector the E2E page object fills.
    expect(input).toHaveAttribute("id", "env-backup-ttl");
  });

  it("carries a valid retention through to the created config", async () => {
    const user = await openAdvancedForm();

    await user.type(screen.getByLabelText("Backup Retention TTL"), "2160h");
    await fillRequiredAndSubmit(user);

    await waitFor(() => expect(submittedConfig()).toMatchObject({}));
    expect(submittedConfig()).toMatchObject({ backup_ttl: "2160h" });
  });

  it("omits the key entirely when left blank", async () => {
    // Blank means "inherit the cluster's policy". Sending `""` or `null` would
    // be a different statement, and `""` is not a valid Go duration.
    const user = await openAdvancedForm();

    await fillRequiredAndSubmit(user);

    await waitFor(() =>
      expect(createEnvironmentMutateAsync).toHaveBeenCalled(),
    );
    const config = submittedConfig();
    expect(config == null || !("backup_ttl" in config)).toBe(true);
  });

  it("blocks submit and shows the reason for a malformed duration", async () => {
    // `30d` is the classic mistake: Go has no day unit, so Velero could not
    // parse it. It must be caught here, not at apply time.
    const user = await openAdvancedForm();

    await user.type(screen.getByLabelText("Backup Retention TTL"), "30d");
    await fillRequiredAndSubmit(user);

    expect(
      await screen.findByText(/positive Go duration using h\/m\/s units/i),
    ).toBeInTheDocument();
    expect(createEnvironmentMutateAsync).not.toHaveBeenCalled();
  });

  it("blocks submit and shows the reason for a value above the Go ceiling", async () => {
    // The validator's second failure mode must reach the field too — a single
    // static refine message would have told the operator the syntax was wrong.
    const user = await openAdvancedForm();

    await user.type(
      screen.getByLabelText("Backup Retention TTL"),
      `${MAX_BACKUP_TTL_HOURS + 1}h`,
    );
    await fillRequiredAndSubmit(user);

    expect(await screen.findByText(/must not exceed/i)).toBeInTheDocument();
    expect(createEnvironmentMutateAsync).not.toHaveBeenCalled();
  });

  it("accepts a compound duration", async () => {
    // `1h30m` is a valid Go duration; the shared validator allows compounds,
    // so the dialog must not be stricter than the backend.
    const user = await openAdvancedForm();

    await user.type(screen.getByLabelText("Backup Retention TTL"), "1h30m");
    await fillRequiredAndSubmit(user);

    await waitFor(() =>
      expect(createEnvironmentMutateAsync).toHaveBeenCalled(),
    );
    expect(submittedConfig()).toMatchObject({ backup_ttl: "1h30m" });
  });
});
