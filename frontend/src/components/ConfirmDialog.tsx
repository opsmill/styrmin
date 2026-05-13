/**
 * ConfirmDialog — in-app replacement for `window.confirm`.
 *
 * Use for destructive admin actions (delete user, delete group, etc.). The
 * default-focus button is "Cancel" so an accidental Enter press does not
 * destroy data; the confirm button uses the destructive variant when the
 * caller flags the action as destructive.
 *
 * Accessibility comes for free from the underlying Base UI Dialog primitive
 * (focus trap, Escape closes, focus restoration on close). We layer on a
 * useEffect that re-focuses the Cancel button each time the dialog opens so
 * that even if the trigger button was already pressed, the keyboard user
 * lands on the safe choice.
 */
import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /**
   * Body content. Strings are wrapped in a `DialogDescription`; richer
   * content (e.g., a paragraph plus a callout) is rendered verbatim.
   */
  description: ReactNode;
  /** Confirm button label. Defaults to "Confirm". */
  confirmLabel?: string;
  /** Cancel button label. Defaults to "Cancel". */
  cancelLabel?: string;
  /**
   * When true, render the confirm button using the destructive variant.
   * Defaults to true since this dialog is intended for destructive flows.
   */
  destructive?: boolean;
  /** Disable both buttons while a mutation is in flight. */
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Test hook for the dialog content root. */
  "data-testid"?: string;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = true,
  busy = false,
  onConfirm,
  onCancel,
  "data-testid": testId = "confirm-dialog",
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  // Pull initial keyboard focus onto Cancel so Enter is a safe choice.
  useEffect(() => {
    if (open) {
      // Defer so Base UI's own focus-trap has settled.
      const id = window.setTimeout(() => cancelRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  function handleOpenChange(next: boolean): void {
    if (!next && !busy) onCancel();
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent data-testid={testId}>
        <DialogHeader>
          <DialogTitle data-testid={`${testId}-title`}>{title}</DialogTitle>
          {typeof description === "string" ? (
            <DialogDescription data-testid={`${testId}-body`}>
              {description}
            </DialogDescription>
          ) : (
            <div
              className="text-sm text-muted-foreground"
              data-testid={`${testId}-body`}
            >
              {description}
            </div>
          )}
        </DialogHeader>
        <DialogFooter>
          <Button
            ref={cancelRef}
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={busy}
            data-testid={`${testId}-cancel`}
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={destructive ? "destructive" : "default"}
            onClick={onConfirm}
            disabled={busy}
            data-testid={`${testId}-confirm`}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
