import { Badge } from "@/components/ui/badge";
import { Circle } from "lucide-react";

type BadgeVariant =
  | "warning"
  | "success"
  | "destructive"
  | "default"
  | "secondary";

interface StatusConfig {
  label: string;
  variant: BadgeVariant;
}

const statusConfig: Record<string, StatusConfig> = {
  // Healthy / positive states
  RUNNING: { label: "Running", variant: "success" },
  SUCCESS: { label: "Success", variant: "success" },
  ACTIVE: { label: "Healthy", variant: "success" },
  active: { label: "Healthy", variant: "success" },
  completed: { label: "Complete", variant: "success" },
  success: { label: "Success", variant: "success" },
  running: { label: "Running", variant: "success" },

  // Warning / in-progress states
  PENDING: { label: "Pending", variant: "warning" },
  pending: { label: "Pending", variant: "warning" },
  in_progress: { label: "In Progress", variant: "warning" },
  creating: { label: "Creating", variant: "warning" },
  updating: { label: "Updating", variant: "warning" },
  scaling: { label: "Scaling", variant: "warning" },
  reconciling: { label: "Reconciling", variant: "warning" },
  restoring: { label: "Restoring", variant: "warning" },
  deleting: { label: "Deleting", variant: "warning" },
  stopping: { label: "Stopping", variant: "warning" },

  // Error / failure states
  FAILED: { label: "Failed", variant: "destructive" },
  failed: { label: "Failed", variant: "destructive" },
  error: { label: "Error", variant: "destructive" },
  degraded: { label: "Degraded", variant: "destructive" },

  // Inactive / neutral states
  inactive: { label: "Inactive", variant: "secondary" },
  stopped: { label: "Stopped", variant: "secondary" },
  unknown: { label: "Unknown", variant: "default" },
};

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status] ?? {
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

/**
 * Returns a Tailwind color class for a status value.
 * Use for card borders, dots, and other color indicators.
 */
export function getStatusColor(status: string): {
  dot: string;
  border: string;
  bg: string;
  text: string;
} {
  const s = status.toLowerCase();

  if (
    s === "running" ||
    s === "success" ||
    s === "active" ||
    s === "completed" ||
    s === "healthy"
  ) {
    return {
      dot: "bg-success",
      border: "border-success/30",
      bg: "bg-success/10",
      text: "text-success",
    };
  }

  if (s === "failed" || s === "error" || s === "degraded") {
    return {
      dot: "bg-destructive",
      border: "border-destructive/30",
      bg: "bg-destructive/10",
      text: "text-destructive",
    };
  }

  if (
    s === "pending" ||
    s === "in_progress" ||
    s === "creating" ||
    s === "updating" ||
    s === "scaling" ||
    s === "reconciling" ||
    s === "restoring" ||
    s === "deleting" ||
    s === "stopping"
  ) {
    return {
      dot: "bg-warning",
      border: "border-warning/30",
      bg: "bg-warning/10",
      text: "text-warning",
    };
  }

  return {
    dot: "bg-muted-foreground",
    border: "border-border",
    bg: "bg-muted",
    text: "text-muted-foreground",
  };
}
