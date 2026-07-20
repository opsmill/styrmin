import { Fragment, type ReactNode } from "react";

/**
 * Wrap every case-insensitive occurrence of `query` inside `text` in a
 * <mark>, so a filtered list shows *why* each row matched. Returns the
 * plain string when the query is empty or has no match.
 */
export function highlightMatch(text: string, query: string): ReactNode {
  const q = query.trim();
  if (!q) return text;

  const parts = text.split(new RegExp(`(${escapeRegExp(q)})`, "gi"));
  if (parts.length === 1) return text;

  return parts.map((part, i) =>
    part.toLowerCase() === q.toLowerCase() ? (
      <mark
        key={i}
        className="rounded-[2px] bg-yellow-200/80 text-inherit dark:bg-yellow-500/30"
      >
        {part}
      </mark>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
