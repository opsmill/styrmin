import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { LOADED_SCOPE_NOTE } from "@/lib/driverVersion";

/**
 * Version-status badges shared by the driver list and detail. The "Latest" pill
 * carries a tooltip clarifying that "newest" is scoped to what's loaded into
 * this Styrmin instance (see LOADED_SCOPE_NOTE).
 */

/** "Latest" pill with the loaded-scope tooltip (the badge is the claim). */
export function LatestBadge() {
  return (
    <Tooltip content={LOADED_SCOPE_NOTE}>
      <Badge variant="success" className="cursor-help">
        Latest
      </Badge>
    </Tooltip>
  );
}

/**
 * "Older version" pill — a plain statement, no tooltip. The loaded-scope caveat
 * belongs to the word "newest" in the accompanying caption, not to this badge.
 */
export function OlderBadge() {
  return <Badge variant="warning">Older version</Badge>;
}
