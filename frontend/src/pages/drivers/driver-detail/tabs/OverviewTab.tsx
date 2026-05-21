import type { DriverVersionDetail } from "../types";

interface OverviewTabProps {
  version: DriverVersionDetail;
}

/**
 * Overview tab — three summary tiles for the selected driver version:
 * Helm chart, Components, Parameters.
 *
 * Per the edge-case rule in the spec, empty underlying data renders an
 * empty-state label per tile rather than a bare "0" or "—".
 */
export function OverviewTab({ version }: OverviewTabProps) {
  const componentSummary = summarizeComponents(version.components);
  const totalParameters = version.parameters.length;
  const requiredParameters = version.parameters.filter(
    (p) => p.default === null || p.default === undefined,
  ).length;

  return (
    <div
      className="grid grid-cols-1 gap-4 md:grid-cols-3"
      data-testid="driver-overview-tiles"
    >
      <SummaryTile title="Helm chart">
        <div className="text-sm">
          <p className="font-mono">
            {version.helmChart.name}{" "}
            <span className="text-muted-foreground">
              {version.helmChart.version}
            </span>
          </p>
          <p
            className="mt-1 truncate text-xs text-muted-foreground"
            title={version.helmChart.repository}
          >
            {version.helmChart.repository}
          </p>
        </div>
      </SummaryTile>

      <SummaryTile title="Components">
        {componentSummary.count === 0 ? (
          <EmptyTileLabel>No components declared</EmptyTileLabel>
        ) : (
          <div className="text-sm">
            <p className="text-2xl font-semibold text-foreground">
              {componentSummary.count}
            </p>
            <p
              className="mt-1 truncate text-xs text-muted-foreground"
              title={componentSummary.names.join(", ")}
            >
              {componentSummary.names.join(", ")}
            </p>
          </div>
        )}
      </SummaryTile>

      <SummaryTile title="Parameters">
        {totalParameters === 0 ? (
          <EmptyTileLabel>No parameters declared</EmptyTileLabel>
        ) : (
          <div className="text-sm">
            <p className="text-2xl font-semibold text-foreground">
              {totalParameters}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {requiredParameters} required
            </p>
          </div>
        )}
      </SummaryTile>
    </div>
  );
}

function SummaryTile({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

function EmptyTileLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-sm italic text-muted-foreground">{children}</p>;
}

interface ComponentsSummary {
  count: number;
  names: string[];
}

/**
 * Defensive shape-check of the JSON `components` declaration per
 * `data-model.md`. The declaration must be a plain object (not an array, not
 * null). Anything else degrades to the empty summary.
 */
function summarizeComponents(
  components: DriverVersionDetail["components"],
): ComponentsSummary {
  if (
    components === null ||
    components === undefined ||
    typeof components !== "object" ||
    Array.isArray(components)
  ) {
    return { count: 0, names: [] };
  }
  const names = Object.keys(components as Record<string, unknown>);
  return { count: names.length, names };
}
