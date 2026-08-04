import { Tooltip, Button } from 'frontend';

// ⚠️ STATIC-CARD LIMITATION
// The exported `Tooltip` wrapper only accepts { content, children, delay,
// className } — it does NOT forward `defaultOpen`/`open` to the underlying
// Base UI Tooltip.Root, and the popup lives in a Portal that opens only on
// hover/focus. In a static headless card the popup will NOT be visible; only
// the trigger renders. Flagged for a provider/cardMode override (or skip).

export const Default = () => (
  <Tooltip content="Redeploy the latest driver version">
    <Button variant="outline">Redeploy</Button>
  </Tooltip>
);

export const RichContent = () => (
  <Tooltip content="Cluster is drifting from its declared state. Reconcile to sync.">
    <Button variant="ghost">Status</Button>
  </Tooltip>
);
