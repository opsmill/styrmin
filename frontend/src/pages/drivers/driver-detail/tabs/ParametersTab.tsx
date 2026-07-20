import type { DriverParameter, DriverVersionDetail } from "../types";

interface ParametersTabProps {
  version: DriverVersionDetail;
}

/**
 * Parameters table — one row per declared parameter. REQUIRED is derived per
 * FR-011 (`default === null || default === undefined`). The empty case renders
 * the empty-state message only — no empty table header (FR-017).
 *
 * Typography is aligned with the driver-detail metadata grid (single `text-sm`
 * body, `text-[13px]` mono, `text-[11px]` uppercase column headers) so the two
 * tables read as one system.
 */
export function ParametersTab({ version }: ParametersTabProps) {
  if (version.parameters.length === 0) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-testid="driver-parameters-empty"
      >
        No parameters declared
      </p>
    );
  }

  return (
    <div
      className="overflow-hidden rounded-lg border border-border"
      data-testid="driver-parameters-table"
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2.5 font-medium">Name</th>
            <th className="px-4 py-2.5 font-medium">Label</th>
            <th className="px-4 py-2.5 font-medium">Kind</th>
            <th className="px-4 py-2.5 font-medium">Required</th>
            <th className="px-4 py-2.5 font-medium">Default</th>
          </tr>
        </thead>
        <tbody>
          {version.parameters.map((param) => (
            <ParameterRow key={param.name} param={param} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ParameterRow({ param }: { param: DriverParameter }) {
  const required = param.default === null || param.default === undefined;
  return (
    <tr
      className="border-b border-border/60 last:border-0"
      data-testid="driver-parameter-row"
      data-parameter-name={param.name}
    >
      <td className="px-4 py-2.5 font-mono text-[13px]">{param.name}</td>
      <td className="px-4 py-2.5">{param.label}</td>
      <td className="px-4 py-2.5 font-mono text-[13px] text-muted-foreground">
        {param.kind}
      </td>
      <td className="px-4 py-2.5">
        {required ? (
          <span className="font-medium">Required</span>
        ) : (
          <span className="text-muted-foreground">Optional</span>
        )}
      </td>
      <td className="px-4 py-2.5 font-mono text-[13px]">
        {formatDefault(param.default)}
      </td>
    </tr>
  );
}

function formatDefault(value: DriverParameter["default"]): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}
