import { cn } from "@/lib/utils";

const TYPE_STYLES: Record<string, string> = {
  string: "bg-destructive/10 text-destructive",
  integer: "bg-primary/10 text-primary",
  boolean: "bg-warning/10 text-warning-foreground",
  select: "bg-success/10 text-success",
};

interface Parameter {
  key: string;
  value: unknown;
  type?: string;
  description?: string;
}

interface ParameterCardsProps {
  parameters: Parameter[];
  title?: string;
  description?: string;
}

export function ParameterCards({
  parameters,
  title,
  description,
}: ParameterCardsProps) {
  return (
    <div className="flex flex-col gap-4">
      {(title || description) && (
        <div className="flex flex-col gap-0.5">
          {title && (
            <span className="text-[13px] font-semibold text-foreground">
              {title}
            </span>
          )}
          {description && (
            <span className="text-xs text-muted-foreground">{description}</span>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        {parameters.map((param) => {
          const typeStr = param.type ?? inferType(param.value);
          const valueStr = String(param.value);
          const isBoolTrue = valueStr === "true";

          return (
            <div
              key={param.key}
              className="flex w-[350px] flex-col gap-1.5 rounded-[10px] bg-surface p-3.5"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-semibold text-foreground">
                  {param.key}
                </span>
                <span
                  className={cn(
                    "rounded-md px-1.5 py-px text-[10px] font-medium",
                    TYPE_STYLES[typeStr] ?? "bg-muted text-muted-foreground",
                  )}
                >
                  {typeStr}
                </span>
              </div>
              <span
                className={cn(
                  "font-mono text-[13px]",
                  typeStr === "boolean" && isBoolTrue
                    ? "text-success"
                    : "text-foreground",
                )}
              >
                {valueStr}
              </span>
              {param.description && (
                <span className="text-[11px] text-muted-foreground">
                  {param.description}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function inferType(value: unknown): string {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "integer";
  return "string";
}
