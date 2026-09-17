import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { APP_NAME, useDocumentTitle } from "./use-document-title";

describe("useDocumentTitle", () => {
  it("suffixes the page name with the product name", () => {
    renderHook(() => useDocumentTitle("Environments"));
    expect(document.title).toBe("Environments · Styrmin");
  });

  it("falls back to the bare product name when the page name is not known yet", () => {
    renderHook(() => useDocumentTitle(null));
    expect(document.title).toBe(APP_NAME);
  });

  it("treats an empty page name as unknown", () => {
    renderHook(() => useDocumentTitle(""));
    expect(document.title).toBe(APP_NAME);
  });

  it("retitles when the page name arrives", () => {
    const { rerender } = renderHook(
      ({ page }: { page: string }) => useDocumentTitle(page),
      { initialProps: { page: "Deployment" } },
    );
    expect(document.title).toBe("Deployment · Styrmin");

    rerender({ page: "postgres-prod" });
    expect(document.title).toBe("postgres-prod · Styrmin");
  });
});
