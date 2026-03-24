import { Badge } from "@/components/ui/badge";
import { Circle } from "lucide-react";

type Status = "PENDING" | "RUNNING" | "FAILED" | "SUCCESS";

const statusConfig: Record<
  Status,
  { label: string; variant: "warning" | "success" | "destructive" | "default" }
> = {
  PENDING: { label: "Pending", variant: "warning" },
  RUNNING: { label: "Running", variant: "success" },
  SUCCESS: { label: "Success", variant: "success" },
  FAILED: { label: "Failed", variant: "destructive" },
};

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status as Status] ?? {
    label: status,
    variant: "default" as const,
  };

  return (
    <Badge variant={config.variant} className="gap-1">
      <Circle className="h-2 w-2 fill-current" />
      {config.label}
    </Badge>
  );
}
