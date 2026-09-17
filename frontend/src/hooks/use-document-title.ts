import { useEffect } from "react";

/** Product name, shown alone in the HTML shell and as the suffix of every page title. */
export const APP_NAME = "Styrmin";

/** Separator between the page name and the product name. */
const SEPARATOR = " · ";

/**
 * Sets the browser tab title to `<page> · Styrmin` for as long as the calling
 * component is mounted.
 *
 * Every page component calls this once, before any early return for loading or
 * error state. Detail pages pass the object's name with a static fallback for
 * the window where the query is still in flight:
 *
 * ```tsx
 * useDocumentTitle(deployment?.name ?? "Deployment");
 * ```
 *
 * A nullish or empty `page` yields the bare product name, which matches the
 * title in `index.html`.
 */
export function useDocumentTitle(page?: string | null): void {
  useEffect(() => {
    document.title =
      page == null || page === "" ? APP_NAME : `${page}${SEPARATOR}${APP_NAME}`;
  }, [page]);
}
