import { describe, it, expect, vi } from "vitest";
import { render, screen, userEvent, waitFor } from "@/test/utils";

import { BackupRetentionForm } from "@/components/environment/BackupRetentionForm";

const NO_DEPLOYMENTS: Array<{ id: string; name: string }> = [];

const ONE_DEPLOYMENT: Array<{ id: string; name: string }> = [
  { id: "d1", name: "deploy-one" },
];

function input(): HTMLInputElement {
  return screen.getByTestId("backup-retention-input") as HTMLInputElement;
}

describe("BackupRetentionForm (016)", () => {
  it("seeds the input from the persisted backup_ttl and enables Save", async () => {
    await render(
      <BackupRetentionForm
        initialBackupTtl="2160h"
        deployments={NO_DEPLOYMENTS}
        onSubmit={vi.fn()}
      />,
    );
    expect(input().value).toBe("2160h");
    expect(screen.getByTestId("backup-retention-current")).toHaveTextContent(
      "Environment policy: 2160h",
    );
    expect(screen.getByTestId("backup-retention-save-button")).toBeEnabled();
    expect(screen.queryByTestId("backup-retention-error")).toBeNull();
  });

  it("renders an empty input and the inherited notice when no policy is set", async () => {
    await render(
      <BackupRetentionForm
        initialBackupTtl={null}
        deployments={NO_DEPLOYMENTS}
        onSubmit={vi.fn()}
      />,
    );
    expect(input().value).toBe("");
    expect(screen.getByTestId("backup-retention-current")).toHaveTextContent(
      /no environment policy set/i,
    );
    // The built-in default is discoverable without saving anything.
    expect(input().placeholder).toContain("720h");
    expect(screen.getByTestId("backup-retention-hint")).toHaveTextContent(
      /leave empty to clear the environment policy/i,
    );
  });

  it("shows the inline error and disables Save for an invalid duration", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    await render(
      <BackupRetentionForm
        initialBackupTtl="720h"
        deployments={ONE_DEPLOYMENT}
        onSubmit={onSubmit}
      />,
    );
    await user.clear(input());
    await user.type(input(), "30d");

    expect(screen.getByTestId("backup-retention-error")).toHaveTextContent(
      /positive Go duration using h\/m\/s units/i,
    );
    expect(screen.getByTestId("backup-retention-save-button")).toBeDisabled();

    // The handler-level guard holds too, not just the disabled attribute.
    await user.click(screen.getByTestId("backup-retention-save-button"));
    expect(
      screen.queryByTestId("redeploy-confirm-dialog"),
    ).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects an all-zero duration", async () => {
    const user = userEvent.setup();
    await render(
      <BackupRetentionForm
        initialBackupTtl={null}
        deployments={NO_DEPLOYMENTS}
        onSubmit={vi.fn()}
      />,
    );
    await user.type(input(), "0h0m0s");
    expect(screen.getByTestId("backup-retention-error")).toBeInTheDocument();
    expect(screen.getByTestId("backup-retention-save-button")).toBeDisabled();
  });

  it("clears the error and re-enables Save once the value becomes valid", async () => {
    const user = userEvent.setup();
    await render(
      <BackupRetentionForm
        initialBackupTtl={null}
        deployments={NO_DEPLOYMENTS}
        onSubmit={vi.fn()}
      />,
    );
    await user.type(input(), "30d");
    expect(screen.getByTestId("backup-retention-save-button")).toBeDisabled();
    await user.clear(input());
    await user.type(input(), "2160h");
    expect(screen.queryByTestId("backup-retention-error")).toBeNull();
    expect(screen.getByTestId("backup-retention-save-button")).toBeEnabled();
  });

  it("submits the edited duration after the redeploy confirmation", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    await render(
      <BackupRetentionForm
        initialBackupTtl="720h"
        deployments={ONE_DEPLOYMENT}
        onSubmit={onSubmit}
      />,
    );
    await user.clear(input());
    await user.type(input(), "2160h");
    await user.click(screen.getByTestId("backup-retention-save-button"));

    expect(screen.getByTestId("redeploy-confirm-dialog")).toBeInTheDocument();
    expect(
      screen.getByTestId("redeploy-confirm-dialog-body"),
    ).toHaveTextContent(/1 deployment will be redeployed: deploy-one/i);

    await user.click(screen.getByTestId("redeploy-confirm-redeploy"));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith("2160h");
    });
  });

  it("submits null when the input is emptied (clears the policy)", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    await render(
      <BackupRetentionForm
        initialBackupTtl="2160h"
        deployments={NO_DEPLOYMENTS}
        onSubmit={onSubmit}
      />,
    );
    await user.clear(input());
    // Blank is the "clear the policy" gesture, not an invalid value.
    expect(screen.queryByTestId("backup-retention-error")).toBeNull();
    expect(screen.getByTestId("backup-retention-save-button")).toBeEnabled();

    await user.click(screen.getByTestId("backup-retention-save-button"));
    await user.click(screen.getByTestId("redeploy-confirm-redeploy"));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(null);
    });
  });

  it("keeps the edited value when Cancel dismisses the confirmation", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    await render(
      <BackupRetentionForm
        initialBackupTtl="720h"
        deployments={ONE_DEPLOYMENT}
        onSubmit={onSubmit}
      />,
    );
    await user.clear(input());
    await user.type(input(), "8760h");
    await user.click(screen.getByTestId("backup-retention-save-button"));
    await user.click(screen.getByTestId("redeploy-confirm-cancel"));
    await waitFor(() => {
      expect(
        screen.queryByTestId("redeploy-confirm-dialog"),
      ).not.toBeInTheDocument();
    });
    expect(input().value).toBe("8760h");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("renders the blocked-warning Alert and disables Save when blockedReason is set", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    await render(
      <BackupRetentionForm
        initialBackupTtl="720h"
        deployments={ONE_DEPLOYMENT}
        onSubmit={onSubmit}
        blockedReason="This environment carries scheduling overrides..."
      />,
    );
    expect(
      screen.getByTestId("backup-retention-blocked-warning"),
    ).toHaveTextContent(/scheduling/i);
    expect(screen.getByTestId("backup-retention-save-button")).toBeDisabled();

    await user.click(screen.getByTestId("backup-retention-save-button"));
    expect(
      screen.queryByTestId("redeploy-confirm-dialog"),
    ).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("surfaces a submitError without clearing the edited value", async () => {
    await render(
      <BackupRetentionForm
        initialBackupTtl="720h"
        deployments={ONE_DEPLOYMENT}
        onSubmit={vi.fn()}
        submitError="server exploded"
      />,
    );
    expect(
      screen.getByTestId("backup-retention-submit-error"),
    ).toHaveTextContent(/server exploded/i);
    expect(input().value).toBe("720h");
  });

  it("flips the Save label to Saving... while a submission is in flight", async () => {
    await render(
      <BackupRetentionForm
        initialBackupTtl="720h"
        deployments={ONE_DEPLOYMENT}
        onSubmit={vi.fn()}
        isSubmitting
      />,
    );
    const save = screen.getByTestId("backup-retention-save-button");
    expect(save).toHaveTextContent("Saving...");
    expect(save).toBeDisabled();
  });

  it("hides Save from a read-only user", async () => {
    await render(
      <BackupRetentionForm
        initialBackupTtl="720h"
        deployments={ONE_DEPLOYMENT}
        onSubmit={vi.fn()}
      />,
      {
        auth: {
          currentUser: {
            id: "ro",
            username: "ro",
            displayName: "Read Only",
            role: "READ_ONLY",
            effectiveRole: "READ_ONLY",
            active: true,
          },
          loading: false,
          refresh: () => Promise.resolve(),
          logout: () => Promise.resolve(),
        },
      },
    );
    expect(screen.queryByTestId("backup-retention-save-button")).toBeNull();
    // The value is still readable — only the write control is gated.
    expect(input().value).toBe("720h");
  });
});
