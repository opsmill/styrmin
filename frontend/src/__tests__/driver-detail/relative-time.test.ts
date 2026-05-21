/**
 * Unit tests for `formatRelativeTime` — the coarse-grained relative-time
 * label used by the driver-detail version list.
 *
 * The helper uses `Date.now()` internally, so each test pins the clock with
 * `vi.useFakeTimers()` + `vi.setSystemTime()` before constructing the
 * absolute target timestamp.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { formatRelativeTime } from "@/pages/drivers/driver-detail/relative-time";

const NOW_ISO = "2026-05-21T12:00:00Z";

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW_ISO));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function relativeTo(seconds: number): string {
    const target = new Date(Date.now() - seconds * 1000);
    return formatRelativeTime(target);
  }

  it("returns 'just now' for very recent timestamps (< 45 s)", () => {
    expect(relativeTo(0)).toBe("just now");
    expect(relativeTo(10)).toBe("just now");
    expect(relativeTo(44)).toBe("just now");
  });

  it("returns minutes-ago for sub-hour deltas", () => {
    expect(relativeTo(60)).toBe("1 minute ago");
    expect(relativeTo(60 * 5)).toBe("5 minutes ago");
    expect(relativeTo(60 * 59)).toBe("59 minutes ago");
  });

  it("returns hours-ago for sub-day deltas", () => {
    expect(relativeTo(60 * 60)).toBe("1 hour ago");
    expect(relativeTo(60 * 60 * 3)).toBe("3 hours ago");
    expect(relativeTo(60 * 60 * 23)).toBe("23 hours ago");
  });

  it("returns days-ago for sub-week deltas", () => {
    expect(relativeTo(60 * 60 * 24)).toBe("1 day ago");
    expect(relativeTo(60 * 60 * 24 * 3)).toBe("3 days ago");
    expect(relativeTo(60 * 60 * 24 * 6)).toBe("6 days ago");
  });

  it("returns weeks-ago for sub-month deltas", () => {
    expect(relativeTo(60 * 60 * 24 * 7)).toBe("1 week ago");
    expect(relativeTo(60 * 60 * 24 * 14)).toBe("2 weeks ago");
    // 4 weeks is the last bucket before rolling into months.
    expect(relativeTo(60 * 60 * 24 * 28)).toBe("4 weeks ago");
  });

  it("returns months-ago for sub-year deltas", () => {
    // The helper rolls into the months bucket once `round(days / 7) >= 5`,
    // which corresponds to ~35 days — not exactly 30. Use 35 days as the
    // first-month boundary.
    expect(relativeTo(60 * 60 * 24 * 35)).toBe("1 month ago");
    expect(relativeTo(60 * 60 * 24 * 30 * 6)).toBe("6 months ago");
  });

  it("returns years-ago for >= 1 year deltas", () => {
    expect(relativeTo(60 * 60 * 24 * 365)).toBe("1 year ago");
    expect(relativeTo(60 * 60 * 24 * 365 * 3)).toBe("3 years ago");
  });

  it("returns an empty string for an invalid date input", () => {
    expect(formatRelativeTime("not a date")).toBe("");
  });

  it("collapses future timestamps to 'just now'", () => {
    const future = new Date(Date.now() + 60 * 60 * 1000);
    expect(formatRelativeTime(future)).toBe("just now");
  });

  it("accepts both Date and ISO-string inputs", () => {
    const fiveMinAgoIso = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiveMinAgoIso)).toBe("5 minutes ago");
  });
});
