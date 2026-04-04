import { Badge } from "@/components/ui/badge";
import { Minus, Plus, Replace } from "lucide-react";

interface ContextChangeItem {
  path: string;
  action: string;
  oldValue?: unknown;
  newValue?: unknown;
}

interface ContextDiffViewProps {
  changes: ContextChangeItem[];
}

const ACTION_CONFIG: Record<
  string,
  { label: string; icon: typeof Plus; className: string }
> = {
  added: { label: "Added", icon: Plus, className: "text-green-600" },
  removed: { label: "Removed", icon: Minus, className: "text-red-600" },
  modified: { label: "Modified", icon: Replace, className: "text-yellow-600" },
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export function ContextDiffView({ changes }: ContextDiffViewProps) {
  if (changes.length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">No changes detected.</p>
    );
  }

  return (
    <div className="space-y-1">
      {changes.map((change) => {
        const config = ACTION_CONFIG[change.action] ?? {
          label: change.action,
          icon: Replace,
          className: "text-muted-foreground",
        };
        const Icon = config.icon;

        return (
          <div key={change.path} className="flex items-start gap-2 text-xs">
            <Icon className={`h-3 w-3 mt-0.5 shrink-0 ${config.className}`} />
            <div className="min-w-0">
              <span className="font-mono font-medium">{change.path}</span>
              {change.action === "modified" && (
                <div className="mt-0.5 space-y-0.5">
                  <div className="text-red-600">
                    <Badge variant="outline" className="text-[10px] px-1 py-0 mr-1">
                      old
                    </Badge>
                    <span className="font-mono break-all">
                      {formatValue(change.oldValue)}
                    </span>
                  </div>
                  <div className="text-green-600">
                    <Badge variant="outline" className="text-[10px] px-1 py-0 mr-1">
                      new
                    </Badge>
                    <span className="font-mono break-all">
                      {formatValue(change.newValue)}
                    </span>
                  </div>
                </div>
              )}
              {change.action === "added" && (
                <span className="font-mono text-green-600 ml-1 break-all">
                  {formatValue(change.newValue)}
                </span>
              )}
              {change.action === "removed" && (
                <span className="font-mono text-red-600 ml-1 break-all">
                  {formatValue(change.oldValue)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
