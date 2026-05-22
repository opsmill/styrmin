/**
 * Format an absolute timestamp as a coarse-grained relative-time label
 * (e.g. "2 days ago", "just now").
 *
 * No external dependency; deliberately advisory in precision. See
 * `specs/012-driver-detail-tabs/research.md` §7 for the rationale.
 */
export function formatRelativeTime(date: Date | string): string {
  const target = typeof date === "string" ? new Date(date) : date;
  const targetMs = target.getTime();
  if (Number.isNaN(targetMs)) {
    return "";
  }

  const deltaSeconds = Math.round((Date.now() - targetMs) / 1000);

  if (deltaSeconds < 0) {
    // Future timestamp — treat as "just now" rather than negative.
    return "just now";
  }

  if (deltaSeconds < 45) {
    return "just now";
  }

  const minutes = Math.round(deltaSeconds / 60);
  if (minutes < 60) {
    return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;
  }

  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  }

  const days = Math.round(hours / 24);
  if (days < 7) {
    return days === 1 ? "1 day ago" : `${days} days ago`;
  }

  const weeks = Math.round(days / 7);
  if (weeks < 5) {
    return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
  }

  const months = Math.round(days / 30);
  if (months < 12) {
    return months === 1 ? "1 month ago" : `${months} months ago`;
  }

  const years = Math.round(days / 365);
  return years === 1 ? "1 year ago" : `${years} years ago`;
}
