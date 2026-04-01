import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
import { AutoRefreshIndicator } from "./AutoRefreshIndicator";

function makeDefaultProps() {
  return {
    enabled: true,
    onToggle: vi.fn(),
    lastRefreshedAt: null as Date | null,
    onRefreshNow: vi.fn(),
  };
}

describe("AutoRefreshIndicator", () => {
  let defaultProps: ReturnType<typeof makeDefaultProps>;

  beforeEach(() => {
    defaultProps = makeDefaultProps();
  });

  it("renders refresh button", async () => {
    await render(<AutoRefreshIndicator {...defaultProps} />);
    expect(
      screen.getByRole("button", { name: "Refresh now" }),
    ).toBeInTheDocument();
  });

  it("calls onRefreshNow when refresh button is clicked", async () => {
    const user = userEvent.setup();
    const onRefreshNow = vi.fn();
    await render(
      <AutoRefreshIndicator {...defaultProps} onRefreshNow={onRefreshNow} />,
    );

    await user.click(screen.getByRole("button", { name: "Refresh now" }));
    expect(onRefreshNow).toHaveBeenCalledOnce();
  });

  it("shows 'Auto' when enabled", async () => {
    await render(<AutoRefreshIndicator {...defaultProps} enabled={true} />);
    expect(screen.getByText("Auto")).toBeInTheDocument();
  });

  it("shows 'Paused' when disabled", async () => {
    await render(<AutoRefreshIndicator {...defaultProps} enabled={false} />);
    expect(screen.getByText("Paused")).toBeInTheDocument();
  });

  it("calls onToggle with false when disabling", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    await render(
      <AutoRefreshIndicator
        {...defaultProps}
        enabled={true}
        onToggle={onToggle}
      />,
    );

    await user.click(screen.getByTitle("Disable auto-refresh"));
    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it("shows time ago when lastRefreshedAt is provided", async () => {
    const recent = new Date(Date.now() - 30000);
    await render(
      <AutoRefreshIndicator {...defaultProps} lastRefreshedAt={recent} />,
    );
    expect(screen.getByText("30s ago")).toBeInTheDocument();
  });

  it("does not show time ago when lastRefreshedAt is null", async () => {
    await render(
      <AutoRefreshIndicator {...defaultProps} lastRefreshedAt={null} />,
    );
    expect(screen.queryByText(/ago/)).toBeNull();
  });
});
