import { describe, it, expect, vi } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders the title", () => {
    render(<EmptyState title="No items" />);
    expect(screen.getByText("No items")).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    render(<EmptyState title="No items" description="Add some items" />);
    expect(screen.getByText("Add some items")).toBeInTheDocument();
  });

  it("does not render description when not provided", () => {
    const { container } = render(<EmptyState title="No items" />);
    expect(container.querySelector("p")).toBeNull();
  });

  it("shows an action button when actionLabel and onAction are provided", () => {
    render(
      <EmptyState title="No items" actionLabel="Add" onAction={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("does not show an action button when actionLabel is missing", () => {
    render(<EmptyState title="No items" onAction={() => {}} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("calls onAction when the action button is clicked", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <EmptyState title="No items" actionLabel="Add" onAction={onAction} />,
    );

    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(onAction).toHaveBeenCalledOnce();
  });
});
