import { Button } from "@/components/ui/button";

import { useDrawerDiff, useDrawerInvalidImages } from "./DrawerDiffContext";

interface Props {
  onDiscard: () => void;
  onReviewApply: () => void;
}

/**
 * Sticky footer rendered at the bottom of `ConfigEditDrawer`.
 *
 * Reads the shared drawer diff (computed once in {@link DrawerDiffProvider})
 * to count pending changes. The footer count, the section-nav dots, and the
 * Review & apply dialog all draw from the same diff result so they cannot
 * disagree on what "changed" means.
 *
 * Both action buttons are disabled when there are no pending changes
 * (FR-013). Review & apply is also disabled while an image override is
 * invalid (018), with a hint naming the components.
 */
export function DrawerFooter({ onDiscard, onReviewApply }: Props) {
  const pendingCount = useDrawerDiff().entries.length;
  const noChanges = pendingCount === 0;
  const invalidImages = useDrawerInvalidImages();
  const blocked = invalidImages.length > 0;

  return (
    <footer
      data-testid="drawer-footer"
      className="sticky bottom-0 z-10 flex items-center justify-between gap-3 border-t border-border bg-background px-6 py-4 shadow-[0_-1px_2px_rgba(15,23,42,0.04)]"
    >
      <div className="min-w-0 space-y-0.5">
        <p
          className="text-sm text-muted-foreground"
          data-testid="drawer-pending-count"
          aria-live="polite"
        >
          {pendingCount === 0
            ? "No pending changes"
            : `${pendingCount} pending change${pendingCount === 1 ? "" : "s"}`}
        </p>
        {blocked && (
          <p
            id="drawer-invalid-hint"
            data-testid="drawer-invalid-hint"
            className="text-xs text-destructive"
          >
            Fix the invalid image reference on {invalidImages.join(", ")} before
            applying.
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onDiscard}
          disabled={noChanges}
          data-testid="drawer-discard-button"
        >
          Discard
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={onReviewApply}
          disabled={noChanges || blocked}
          aria-describedby={blocked ? "drawer-invalid-hint" : undefined}
          data-testid="drawer-review-apply-button"
        >
          Review &amp; apply
        </Button>
      </div>
    </footer>
  );
}
