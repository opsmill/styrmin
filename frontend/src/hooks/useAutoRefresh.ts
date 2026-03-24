import { useState, useEffect, useRef, useCallback } from "react";

interface UseAutoRefreshOptions {
  /** Function to call on each refresh (e.g. urql reexecute) */
  onRefresh: () => void;
  /** Interval in ms, default 10000 */
  interval?: number;
  /** Start enabled, default true */
  enabled?: boolean;
}

interface UseAutoRefreshReturn {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
  lastRefreshedAt: Date | null;
  refreshNow: () => void;
}

export function useAutoRefresh({
  onRefresh,
  interval = 10_000,
  enabled: initialEnabled = true,
}: UseAutoRefreshOptions): UseAutoRefreshReturn {
  const [enabled, setEnabled] = useState(initialEnabled);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onRefreshRef = useRef(onRefresh);

  // Keep the callback ref up to date without restarting the interval
  useEffect(() => {
    onRefreshRef.current = onRefresh;
  }, [onRefresh]);

  const doRefresh = useCallback(() => {
    onRefreshRef.current();
    setLastRefreshedAt(new Date());
  }, []);

  const refreshNow = useCallback(() => {
    doRefresh();
    // Reset the interval so the next tick is a full interval away
    if (enabled && intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = setInterval(doRefresh, interval);
    }
  }, [doRefresh, enabled, interval]);

  useEffect(() => {
    if (enabled) {
      intervalRef.current = setInterval(doRefresh, interval);
    }
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled, interval, doRefresh]);

  return { enabled, setEnabled, lastRefreshedAt, refreshNow };
}
