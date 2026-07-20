import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { highlightMatch } from "@/lib/highlight";

describe("highlightMatch", () => {
  it("wraps the matched substring in a <mark>", () => {
    render(<div data-testid="out">{highlightMatch("infrahub", "fra")}</div>);
    const mark = screen.getByText("fra");
    expect(mark.tagName).toBe("MARK");
    expect(screen.getByTestId("out")).toHaveTextContent("infrahub");
  });

  it("is case-insensitive", () => {
    render(<div>{highlightMatch("Infrahub", "INFRA")}</div>);
    expect(screen.getByText("Infra").tagName).toBe("MARK");
  });

  it("returns plain text with no <mark> when the query is empty", () => {
    const { container } = render(<div>{highlightMatch("infrahub", "")}</div>);
    expect(container.querySelector("mark")).toBeNull();
    expect(container).toHaveTextContent("infrahub");
  });

  it("returns plain text with no <mark> when there is no match", () => {
    const { container } = render(
      <div>{highlightMatch("infrahub", "xyz")}</div>,
    );
    expect(container.querySelector("mark")).toBeNull();
  });
});
