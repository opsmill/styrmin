import { describe, it, expect, vi } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
import { ErrorState } from "./ErrorState";

describe("ErrorState", () => {
  it("renders the default title and message", async () => {
    await render(<ErrorState message="Something broke" />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });

  it("renders a custom title", async () => {
    await render(<ErrorState title="Oops" message="Bad request" />);
    expect(screen.getByText("Oops")).toBeInTheDocument();
  });

  it("shows a retry button when onRetry is provided", async () => {
    await render(<ErrorState message="fail" onRetry={() => {}} />);
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("does not show a retry button when onRetry is not provided", async () => {
    await render(<ErrorState message="fail" />);
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("calls onRetry when the retry button is clicked", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    await render(<ErrorState message="fail" onRetry={onRetry} />);

    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
