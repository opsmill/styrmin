import { Button } from "@/components/ui/button";
import { Inbox, Package } from "lucide-react";

interface EmptyStateProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: "inbox" | "package";
  comingSoon?: boolean;
}

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
  icon = "inbox",
  comingSoon,
}: EmptyStateProps) {
  const Icon = icon === "package" ? Package : Inbox;

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface">
        <Icon className="h-7 w-7 text-muted-foreground" />
      </div>
      <div className="flex flex-col items-center gap-1.5">
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {description && (
          <p className="max-w-sm text-[13px] text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {comingSoon && (
        <div className="flex items-center gap-1.5 rounded-lg bg-muted px-4 py-2">
          <div className="h-1.5 w-1.5 rounded-full bg-primary" />
          <span className="text-xs font-medium text-muted-foreground">
            Coming soon — currently in development
          </span>
        </div>
      )}
      {actionLabel && onAction && (
        <Button variant="outline" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
