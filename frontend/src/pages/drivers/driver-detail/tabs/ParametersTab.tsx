import { Badge } from "@/components/ui/badge";
import type { DriverParameter, DriverVersionDetail } from "../types";

interface ParametersTabProps {
  version: DriverVersionDetail;
}

/**
 * Parameters tab — structured table per FR-002 / FR-008 / FR-011.
 *
 * REQUIRED is derived per FR-011 (`default === null || default === undefined`).
 * Per FR-017, the empty case renders the empty-state message only — no empty
 * table header.
 */
export function ParametersTab({ version }: ParametersTabProps) {
  if (version.parameters.length === 0) {
    return (
      <p
        className="text-sm italic text-muted-foreground"
        data-testid="driver-parameters-empty"
      >
        No parameters declared
      </p>
    );
  }

  return (
    <div
      className="overflow-hidden rounded-md border border-border"
      data-testid="driver-parameters-table"
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/50 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-2">Name</th>
            <th className="px-4 py-2">Label</th>
            <th className="px-4 py-2">Kind</th>
            <th className="px-4 py-2">Required</th>
            <th className="px-4 py-2">Default</th>
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
      className="border-b border-border last:border-0"
      data-testid="driver-parameter-row"
      data-parameter-name={param.name}
    >
      <td className="px-4 py-2 font-mono">{param.name}</td>
      <td className="px-4 py-2">{param.label}</td>
      <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
        {param.kind}
      </td>
      <td className="px-4 py-2">
        {required ? (
          <Badge
            variant="destructive"
            className="px-1.5 py-0 text-[10px] uppercase"
          >
            Required
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">Optional</span>
        )}
      </td>
      <td className="px-4 py-2 font-mono text-xs">
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
