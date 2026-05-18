import { describe, it, expect, vi } from "vitest";
import { render, screen, userEvent, waitFor, within } from "@/test/utils";

import { EnvVarsForm } from "@/components/environment/EnvVarsForm";

const NO_DEPLOYMENTS: Array<{ id: string; name: string; internal: boolean }> =
  [];

const ONE_DEPLOYMENT: Array<{ id: string; name: string; internal: boolean }> = [
  { id: "d1", name: "deploy-one", internal: false },
];

describe("EnvVarsForm", () => {
  it("seeds rows from initialEnvVars and enables Save when valid", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    await render(
      <EnvVarsForm
        initialEnvVars={[{ name: "LOG_LEVEL", value: "info" }]}
        deployments={NO_DEPLOYMENTS}
        onSubmit={onSubmit}
      />,
    );

    const rows = screen.getByTestId("env-vars-form-rows");
    expect(within(rows).getAllByTestId("env-vars-form-row")).toHaveLength(1);

    const save = screen.getByTestId("env-vars-form-save-button");
    expect(save).toBeEnabled();

    // Add a new valid row → still enabled.
    await user.click(screen.getByTestId("env-vars-form-add-button"));
    const nameInputs = screen.getAllByTestId("env-var-name-input");
    const valueInputs = screen.getAllByTestId("env-var-value-input");
    await user.type(nameInputs[1], "EXTRA");
    await user.type(valueInputs[1], "x");
    expect(save).toBeEnabled();
  });

  it("shows inline error and disables Save for an invalid name", async () => {
    const user = userEvent.setup();
    await render(
      <EnvVarsForm
        initialEnvVars={[]}
        deployments={NO_DEPLOYMENTS}
        onSubmit={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId("env-vars-form-add-button"));
    const nameInput = screen.getByTestId("env-var-name-input");
    await user.type(nameInput, "1invalid");
    expect(screen.getByTestId("env-var-name-error")).toHaveTextContent(
      /must match/i,
    );
    expect(screen.getByTestId("env-vars-form-save-button")).toBeDisabled();
  });

  it("flags duplicate names and disables Save", async () => {
    const user = userEvent.setup();
    await render(
      <EnvVarsForm
        initialEnvVars={[
          { name: "FOO", value: "1" },
          { name: "FOO", value: "2" },
        ]}
        deployments={NO_DEPLOYMENTS}
        onSubmit={vi.fn()}
      />,
    );
    const errors = await screen.findAllByTestId("env-var-name-error");
    expect(errors.length).toBeGreaterThanOrEqual(2);
    for (const e of errors) {
      expect(e).toHaveTextContent(/duplicate/i);
    }
    expect(screen.getByTestId("env-vars-form-save-button")).toBeDisabled();
    void user; // ensure userEvent imported
  });

  it("flags an oversized value and disables Save", async () => {
    const big = "a".repeat(64 * 1024 + 1);
    await render(
      <EnvVarsForm
        initialEnvVars={[{ name: "BIG", value: big }]}
        deployments={NO_DEPLOYMENTS}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByTestId("env-var-value-error")).toHaveTextContent(
      /exceeds/i,
    );
    expect(screen.getByTestId("env-vars-form-save-button")).toBeDisabled();
  });

  it("opens the redeploy dialog on Save with valid rows; Cancel keeps the form edited", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    await render(
      <EnvVarsForm
        initialEnvVars={[{ name: "LOG_LEVEL", value: "info" }]}
        deployments={ONE_DEPLOYMENT}
        onSubmit={onSubmit}
      />,
    );
    await user.click(screen.getByTestId("env-vars-form-save-button"));
    expect(screen.getByTestId("redeploy-confirm-dialog")).toBeInTheDocument();
    expect(
      screen.getByTestId("redeploy-confirm-dialog-body"),
    ).toHaveTextContent(/1 deployment will be redeployed: deploy-one/i);

    await user.click(screen.getByTestId("redeploy-confirm-cancel"));
    await waitFor(() => {
      expect(
        screen.queryByTestId("redeploy-confirm-dialog"),
      ).not.toBeInTheDocument();
    });
    // The row state survived.
    const nameInput = screen.getByTestId(
      "env-var-name-input",
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("LOG_LEVEL");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("calls onSubmit with the full env-vars payload on Redeploy", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    await render(
      <EnvVarsForm
        initialEnvVars={[{ name: "LOG_LEVEL", value: "info" }]}
        deployments={ONE_DEPLOYMENT}
        onSubmit={onSubmit}
      />,
    );
    await user.click(screen.getByTestId("env-vars-form-save-button"));
    await user.click(screen.getByTestId("redeploy-confirm-redeploy"));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith([
        { name: "LOG_LEVEL", value: "info" },
      ]);
    });
  });

  it("renders a submitError notice without clearing rows", async () => {
    await render(
      <EnvVarsForm
        initialEnvVars={[{ name: "LOG_LEVEL", value: "info" }]}
        deployments={ONE_DEPLOYMENT}
        onSubmit={vi.fn()}
        submitError="server exploded"
      />,
    );
    expect(screen.getByTestId("env-vars-form-error")).toHaveTextContent(
      /server exploded/i,
    );
    const nameInput = screen.getByTestId(
      "env-var-name-input",
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("LOG_LEVEL");
  });

  // Regression: review H2. The v1 form cannot map nested
  // ``dedicated_ingress`` / ``scheduling`` overrides into
  // ``UpdateEnvironmentInput``, so submitting under full-replacement
  // semantics would silently clear them. The form receives a
  // ``blockedReason`` from its parent and MUST render a warning Alert
  // + disable Save when present. See ADR-012 §"Decision 2".
  it("renders the blocked-warning Alert and disables Save when blockedReason is set", async () => {
    const onSubmit = vi.fn();
    await render(
      <EnvVarsForm
        initialEnvVars={[{ name: "LOG_LEVEL", value: "info" }]}
        deployments={ONE_DEPLOYMENT}
        onSubmit={onSubmit}
        blockedReason="This environment carries dedicated_ingress overrides..."
      />,
    );
    expect(
      screen.getByTestId("env-vars-form-blocked-warning"),
    ).toHaveTextContent(/dedicated_ingress/i);
    expect(screen.getByTestId("env-vars-form-save-button")).toBeDisabled();

    // Even attempting a click MUST NOT open the confirm dialog or call
    // onSubmit — the disabled attribute prevents the click event, but
    // we also pin the handler-level guard.
    const user = userEvent.setup();
    await user.click(screen.getByTestId("env-vars-form-save-button"));
    expect(
      screen.queryByTestId("redeploy-confirm-dialog"),
    ).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not render the blocked-warning Alert when blockedReason is null", async () => {
    await render(
      <EnvVarsForm
        initialEnvVars={[{ name: "LOG_LEVEL", value: "info" }]}
        deployments={ONE_DEPLOYMENT}
        onSubmit={vi.fn()}
        blockedReason={null}
      />,
    );
    expect(
      screen.queryByTestId("env-vars-form-blocked-warning"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("env-vars-form-save-button")).toBeEnabled();
  });
});
