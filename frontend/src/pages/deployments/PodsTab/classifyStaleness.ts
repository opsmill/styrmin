export type Staleness = "fresh" | "stale" | "not_reporting";

const STALE_AFTER_MS = 30_000;
const NOT_REPORTING_AFTER_MS = 120_000;

export function classifyStaleness(
  lastPolledAt: string | null | undefined,
  now: Date,
): Staleness {
  if (!lastPolledAt) return "not_reporting";
  const polled = new Date(lastPolledAt).getTime();
  if (Number.isNaN(polled)) return "not_reporting";
  const ageMs = now.getTime() - polled;
  if (ageMs >= NOT_REPORTING_AFTER_MS) return "not_reporting";
  if (ageMs >= STALE_AFTER_MS) return "stale";
  return "fresh";
}
