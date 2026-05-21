import type { DriverAction } from "../types";

interface ActionsTabProps {
  actions: ReadonlyArray<DriverAction>;
}

/**
 * Actions tab — one card per declared action per FR-010 / FR-019.
 *
 * Each card shows the action name (mono, matches version-number visual style),
 * its location (smaller mono), and its description as body text. Never as raw
 * JSON.
 */
export function ActionsTab({ actions }: ActionsTabProps) {
  if (actions.length === 0) {
    return (
      <p
        className="text-sm italic text-muted-foreground"
        data-testid="driver-actions-empty"
      >
        No actions declared
      </p>
    );
  }

  return (
    <div
      className="grid grid-cols-1 gap-3 md:grid-cols-2"
      data-testid="driver-actions-list"
    >
      {actions.map((action) => (
        <ActionCard key={action.id} action={action} />
      ))}
    </div>
  );
}

function ActionCard({ action }: { action: DriverAction }) {
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4"
      data-testid="driver-action-card"
      data-action-id={action.id}
    >
      <div className="flex flex-col gap-1">
        <h3 className="font-mono text-sm font-semibold text-foreground">
          {action.name}
        </h3>
        <p
          className="truncate font-mono text-xs text-muted-foreground"
          title={action.location}
        >
          {action.location}
        </p>
      </div>
      <p className="text-sm text-foreground">{action.description}</p>
    </div>
  );
}
