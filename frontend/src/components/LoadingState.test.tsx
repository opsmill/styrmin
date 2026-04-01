import { describe, it, expect } from "vitest";
import { render, screen } from "@/test/utils";
import { LoadingState } from "./LoadingState";

describe("LoadingState", () => {
  it("renders the default loading message", async () => {
    await render(<LoadingState />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders a custom loading message", async () => {
    await render(<LoadingState message="Fetching data..." />);
    expect(screen.getByText("Fetching data...")).toBeInTheDocument();
  });
});
