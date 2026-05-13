import { describe, it, expect, vi } from "vitest";
import { render, screen, userEvent } from "@/test/utils";

import { ConfirmDialog } from "@/components/ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders the title and description text", async () => {
    await render(
      <ConfirmDialog
        open
        title="Delete user?"
        description="This will permanently delete the user."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByTestId("confirm-dialog-title")).toHaveTextContent(
      "Delete user?",
    );
    expect(screen.getByTestId("confirm-dialog-body")).toHaveTextContent(
      "This will permanently delete the user.",
    );
  });

  it("invokes onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    await render(
      <ConfirmDialog
        open
        title="Delete?"
        description="Body."
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    const ue = userEvent.setup();
    await ue.click(screen.getByTestId("confirm-dialog-confirm"));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("invokes onCancel when the cancel button is clicked", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    await render(
      <ConfirmDialog
        open
        title="Delete?"
        description="Body."
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    const ue = userEvent.setup();
    await ue.click(screen.getByTestId("confirm-dialog-cancel"));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("disables both buttons while busy", async () => {
    await render(
      <ConfirmDialog
        open
        busy
        title="Delete?"
        description="Body."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByTestId("confirm-dialog-confirm")).toBeDisabled();
    expect(screen.getByTestId("confirm-dialog-cancel")).toBeDisabled();
  });

  it("applies the destructive variant by default", async () => {
    await render(
      <ConfirmDialog
        open
        title="Delete?"
        description="Body."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    // The destructive variant exposes a known className token in the
    // shared Button component; assert on its presence rather than the
    // entire class string so this stays resilient.
    const confirm = screen.getByTestId("confirm-dialog-confirm");
    expect(confirm.className).toMatch(/destructive/i);
  });

  it("invokes onCancel when the dialog is dismissed via Escape", async () => {
    const onCancel = vi.fn();
    await render(
      <ConfirmDialog
        open
        title="Delete?"
        description="Body."
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const ue = userEvent.setup();
    await ue.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalled();
  });
});
