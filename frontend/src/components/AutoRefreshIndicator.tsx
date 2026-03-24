import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

interface AutoRefreshIndicatorProps {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  lastRefreshedAt: Date | null;
  onRefreshNow: () => void;
}

function formatTimeAgo(date: Date): string {
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}

export function AutoRefreshIndicator({
  enabled,
  onToggle,
  lastRefreshedAt,
  onRefreshNow,
}: AutoRefreshIndicatorProps) {
  const [, setTick] = useState(0);

  // Update the "Xs ago" text every second
  useEffect(() => {
    if (!lastRefreshedAt) return;
    const timer = setInterval(() => setTick((t) => t + 1), 1_000);
    return () => clearInterval(timer);
  }, [lastRefreshedAt]);

  return (
    <div className="flex items-center gap-1.5">
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8"
        onClick={onRefreshNow}
        title="Refresh now"
      >
        <RefreshCw className="h-3.5 w-3.5" />
      </Button>
      {lastRefreshedAt && (
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {formatTimeAgo(lastRefreshedAt)}
        </span>
      )}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 px-2 text-xs gap-1.5"
        onClick={() => onToggle(!enabled)}
        title={enabled ? "Disable auto-refresh" : "Enable auto-refresh"}
      >
        <span
          className={`h-2 w-2 rounded-full ${enabled ? "bg-green-500" : "bg-muted-foreground/40"}`}
        />
        {enabled ? "Auto" : "Paused"}
      </Button>
    </div>
  );
}
