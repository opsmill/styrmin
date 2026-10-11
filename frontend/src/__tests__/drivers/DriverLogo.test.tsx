import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { DriverLogo } from "@/pages/drivers/DriverLogo";

const LOGO = "https://example.com/logo.svg";
const OTHER_LOGO = "https://example.com/other.png";

function logo(): HTMLElement {
  return screen.getByTestId("driver-logo");
}

function image(): HTMLImageElement {
  const img = logo().querySelector("img");
  expect(img).not.toBeNull();
  return img!;
}

describe("DriverLogo", () => {
  it("shows the package icon over the hidden image until the image loads", () => {
    render(<DriverLogo icon={LOGO} />);
    expect(logo()).toHaveAttribute("data-logo-state", "loading");
    expect(image()).toHaveAttribute("src", LOGO);
    expect(image()).toHaveAttribute("alt", "");
    expect(image()).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image()).toHaveClass("opacity-0");
    expect(logo().querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("shows the image on a white tile once it has loaded", () => {
    render(<DriverLogo icon={LOGO} />);
    fireEvent.load(image());
    expect(logo()).toHaveAttribute("data-logo-state", "image");
    expect(image()).not.toHaveClass("opacity-0");
    expect(logo().querySelector("svg")).toBeNull();
    expect(logo()).toHaveClass("bg-white");
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
    expect(logo()).not.toHaveClass("bg-white");
  });

  it("switches to the fallback when the image fails to load", () => {
    render(<DriverLogo icon={LOGO} />);
    fireEvent.error(image());
    expect(logo()).toHaveAttribute("data-logo-state", "fallback");
    expect(logo().querySelector("img")).toBeNull();
  });

  it("starts loading again when icon changes after a load error", () => {
    const { rerender } = render(<DriverLogo icon={LOGO} />);
    fireEvent.error(image());
    expect(logo()).toHaveAttribute("data-logo-state", "fallback");

    rerender(<DriverLogo icon={OTHER_LOGO} />);
    expect(logo()).toHaveAttribute("data-logo-state", "loading");
    expect(image()).toHaveAttribute("src", OTHER_LOGO);
  });

  it("loads lazily unless asked to load eagerly", () => {
    const { rerender } = render(<DriverLogo icon={LOGO} />);
    expect(image()).toHaveAttribute("loading", "lazy");
    rerender(<DriverLogo icon={LOGO} loading="eager" />);
    expect(image()).toHaveAttribute("loading", "eager");
  });

  it("keeps the same frame size in every state", () => {
    const { rerender } = render(<DriverLogo icon={LOGO} size="sm" />);
    expect(logo()).toHaveClass("h-5", "w-5");
    fireEvent.load(image());
    expect(logo()).toHaveClass("h-5", "w-5");
    rerender(<DriverLogo icon={null} size="sm" />);
    expect(logo()).toHaveClass("h-5", "w-5");
  });
});
