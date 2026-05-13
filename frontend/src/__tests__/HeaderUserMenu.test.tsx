import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the router module so HeaderUserMenu's useNavigate() resolves to a stub.
const { navigateMock } = vi.hoisted(() => ({
  navigateMock: vi.fn(() => Promise.resolve()),
}));

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>(
    "@tanstack/react-router",
  );
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

import { HeaderUserMenu } from "@/components/HeaderUserMenu";
import type { CurrentUser } from "@/auth/AuthProvider";

function makeUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: "u1",
    username: "alice",
    displayName: "Alice Wonderland",
    role: "READ_ONLY",
    effectiveRole: "ADMIN",
    active: true,
    ...overrides,
  };
}

describe("HeaderUserMenu", () => {
  beforeEach(() => {
    navigateMock.mockClear();
  });

  it("renders the display name and role badge derived from effectiveRole", () => {
    const user = makeUser({
      displayName: "Alice",
      role: "READ_ONLY",
      effectiveRole: "ADMIN",
    });
    render(<HeaderUserMenu user={user} onLogout={vi.fn()} />);

    expect(screen.getByTestId("header-user-display-name")).toHaveTextContent(
      "Alice",
    );
    // The badge must reflect effectiveRole (ADMIN, rendered via roleLabel
    // as "Admin"), not the direct role (READ_ONLY).
    expect(screen.getByTestId("header-user-role-badge")).toHaveTextContent(
      "Admin",
    );
    // The raw enum is still available in a tooltip for context.
    expect(screen.getByTestId("header-user-role-badge")).toHaveAttribute(
      "title",
      "ADMIN",
    );
  });

  it("truncates display names longer than 20 chars", () => {
    const long = "A".repeat(30);
    const user = makeUser({ displayName: long });
    render(<HeaderUserMenu user={user} onLogout={vi.fn()} />);

    const rendered =
      screen.getByTestId("header-user-display-name").textContent ?? "";
    expect(rendered.length).toBeLessThanOrEqual(20);
    expect(rendered).not.toEqual(long);
  });

  it("invokes the supplied onLogout when the Logout menu item is clicked", async () => {
    const onLogout = vi.fn(() => Promise.resolve());
    render(<HeaderUserMenu user={makeUser()} onLogout={onLogout} />);

    const ue = userEvent.setup();
    await ue.click(screen.getByTestId("header-user-menu-trigger"));

    const logoutItem = await screen.findByTestId("header-user-menu-logout");
    await ue.click(logoutItem);

    expect(onLogout).toHaveBeenCalledTimes(1);
  });
});
