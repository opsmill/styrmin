import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoRefresh } from "./useAutoRefresh";

describe("useAutoRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls onRefresh at the specified interval", () => {
    const onRefresh = vi.fn();
    renderHook(() => useAutoRefresh({ onRefresh, interval: 5000 }));

    expect(onRefresh).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onRefresh).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onRefresh).toHaveBeenCalledTimes(2);
  });

  it("does not call onRefresh when disabled", () => {
    const onRefresh = vi.fn();
    renderHook(() =>
      useAutoRefresh({ onRefresh, interval: 5000, enabled: false }),
    );

    act(() => {
      vi.advanceTimersByTime(15000);
    });
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("stops calling onRefresh when toggled off", () => {
    const onRefresh = vi.fn();
    const { result } = renderHook(() =>
      useAutoRefresh({ onRefresh, interval: 5000 }),
    );

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onRefresh).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setEnabled(false);
    });

    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("refreshNow triggers an immediate refresh and updates lastRefreshedAt", () => {
    const onRefresh = vi.fn();
    const { result } = renderHook(() =>
      useAutoRefresh({ onRefresh, interval: 10000 }),
    );

    expect(result.current.lastRefreshedAt).toBeNull();

    act(() => {
      result.current.refreshNow();
    });

    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(result.current.lastRefreshedAt).toBeInstanceOf(Date);
  });

  it("cleans up interval on unmount", () => {
    const onRefresh = vi.fn();
    const { unmount } = renderHook(() =>
      useAutoRefresh({ onRefresh, interval: 5000 }),
    );

    unmount();

    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
