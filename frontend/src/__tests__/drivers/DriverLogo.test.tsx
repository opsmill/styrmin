import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { DriverLogo } from "@/pages/drivers/DriverLogo";

const LOGO = "https://example.com/logo.svg";
const OTHER_LOGO = "https://example.com/other.png";

function logo(): HTMLElement {
  return screen.getByTestId("driver-logo");
}

describe("DriverLogo", () => {
  it("renders the image when icon is set", () => {
    render(<DriverLogo icon={LOGO} />);
    expect(logo()).toHaveAttribute("data-logo-state", "image");
    const img = logo().querySelector("img");
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute("src", LOGO);
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("referrerpolicy", "no-referrer");
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["an empty string", ""],
  ])("renders the fallback when icon is %s", (_label, icon) => {
    render(<DriverLogo icon={icon} />);
    expect(logo()).toHaveAttribute("data-logo-state", "fallback");
    expect(logo().querySelector("img")).toBeNull();
    expect(logo().querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("switches to the fallback when the image fails to load", () => {
    render(<DriverLogo icon={LOGO} />);
    fireEvent.error(logo().querySelector("img")!);
    expect(logo()).toHaveAttribute("data-logo-state", "fallback");
    expect(logo().querySelector("img")).toBeNull();
  });

  it("returns to the image state when icon changes after a load error", () => {
    const { rerender } = render(<DriverLogo icon={LOGO} />);
    fireEvent.error(logo().querySelector("img")!);
    expect(logo()).toHaveAttribute("data-logo-state", "fallback");

    rerender(<DriverLogo icon={OTHER_LOGO} />);
    expect(logo()).toHaveAttribute("data-logo-state", "image");
    expect(logo().querySelector("img")).toHaveAttribute("src", OTHER_LOGO);
  });

  it("keeps the same frame size in both states", () => {
    const { rerender } = render(<DriverLogo icon={LOGO} size="sm" />);
    const imageClasses = logo().className;
    rerender(<DriverLogo icon={null} size="sm" />);
    expect(logo().className).toBe(imageClasses);
  });
});
