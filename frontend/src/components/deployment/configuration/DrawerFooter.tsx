import { useStore } from "@tanstack/react-form";
import type { UpdateDeploymentInput } from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { diff } from "@/lib/config-diff";
import type { DriverParameterSchema } from "@/lib/configuration-types";

/**
 * Minimal TanStack Form handle surface this component cares about.
 *
 * The drawer (T034) owns the typed `useForm` instance; this helper only needs
 * to subscribe to the form store and read the current values to compute the
 * pending-change count. Keeping the prop typed against a structural slice
 * (rather than the full `FormApi<…>` generic) avoids cascading the form's
 * generic parameter list through every consumer.
 */
interface FormLike {
  store: Parameters<typeof useStore>[0];
}

interface Props {
  form: FormLike;
  /**
   * Snapshot of the form's initial values captured at mount. Used as the
   * "before" side of the diff so the pending-change count matches what the
   * Review & apply dialog will eventually show (T042) — they MUST share the
   * same diff helper to avoid divergent counts.
   */
  initialValues: UpdateDeploymentInput;
  driverSchema: DriverParameterSchema;
  onDiscard: () => void;
  onReviewApply: () => void;
}

/**
 * Sticky footer rendered at the bottom of `ConfigEditDrawer`.
 *
 * Subscribes to the form store via `useStore` with a selector keyed on
 * `state.values` — that's the minimum subscription that triggers a re-render
 * when a user edit changes a field's value. We then run the canonical
 * `diff()` helper to count pending changes; this guarantees the footer count,
 * the section-nav dot logic (T033), and the Review & apply dialog (T042) all
 * agree on what "changed" means.
 *
 * Both action buttons are disabled when `pendingCount === 0` per FR-013.
 */
export function DrawerFooter({
  form,
  initialValues,
  driverSchema,
  onDiscard,
  onReviewApply,
}: Props) {
  const currentValues = useStore(
    form.store,
    (s) => (s as { values: UpdateDeploymentInput }).values,
  );

  const pendingCount = diff(initialValues, currentValues, driverSchema).entries
    .length;

  const noChanges = pendingCount === 0;

  return (
    <footer
      data-testid="drawer-footer"
      className="sticky bottom-0 z-10 flex items-center justify-between gap-3 border-t border-border bg-background px-6 py-4 shadow-[0_-1px_2px_rgba(15,23,42,0.04)]"
    >
      <p
        className="text-sm text-muted-foreground"
        data-testid="drawer-pending-count"
        aria-live="polite"
      >
        {pendingCount === 0
          ? "No pending changes"
          : `${pendingCount} pending change${pendingCount === 1 ? "" : "s"}`}
      </p>
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
          disabled={noChanges}
          data-testid="drawer-review-apply-button"
        >
          Review &amp; apply
        </Button>
      </div>
    </footer>
  );
}
