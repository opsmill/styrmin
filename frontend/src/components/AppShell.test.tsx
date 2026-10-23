import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, userEvent, within } from "@/test/utils";
import { AppShell } from "./AppShell";
import {
  AuthContext,
  type AuthContextValue,
  type CurrentUser,
} from "@/auth/AuthProvider";
import type { Role } from "@/generated/graphql";

function makeAuth(role: Role | null): AuthContextValue {
  const currentUser: CurrentUser | null =
    role === null
      ? null
      : {
          id: "u",
          username: "u",
          displayName: "U",
          role,
          effectiveRole: role,
          active: true,
        };
  return {
    currentUser,
    loading: false,
    refresh: () => Promise.resolve(),
    logout: () => Promise.resolve(),
  };
}

function Shell({ role = null }: { role?: Role | null } = {}) {
  return (
    <AuthContext.Provider value={makeAuth(role)}>
      <AppShell />
    </AuthContext.Provider>
  );
}

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    get length() {
      return Object.keys(store).length;
    },
    key: vi.fn(() => null),
  };
})();

describe("AppShell", () => {
  beforeAll(() => {
    vi.stubGlobal("localStorage", localStorageMock);
  });

  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
  });

  it("renders top-level navigation links", async () => {
    await render(<Shell />);
    expect(screen.getByText("Environments")).toBeInTheDocument();
    expect(screen.getByText("Drivers")).toBeInTheDocument();
  });

  it("renders Clusters and Backup Storage in the bottom nav regardless of role", async () => {
    await render(<Shell />);
    expect(screen.getByText("Clusters")).toBeInTheDocument();
    expect(screen.getByText("Backup Storage")).toBeInTheDocument();
  });

  it("orders the bottom nav as Clusters → Backup Storage → Settings", async () => {
    await render(<Shell role="ADMIN" />);
    const clusters = screen.getByText("Clusters");
    const backup = screen.getByText("Backup Storage");
    const settings = screen.getByText("Settings");
    expect(
      clusters.compareDocumentPosition(backup) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      backup.compareDocumentPosition(settings) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("hides Settings for non-admin users", async () => {
    await render(<Shell role="READ_WRITE" />);
    expect(screen.queryByText("Settings")).toBeNull();
  });

  it("hides Settings for unauthenticated context", async () => {
    await render(<Shell />);
    expect(screen.queryByText("Settings")).toBeNull();
  });

  it("shows Settings for ADMIN users", async () => {
    await render(<Shell role="ADMIN" />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders the Styrmin brand name", async () => {
    await render(<Shell />);
    expect(screen.getByText("Styrmin")).toBeInTheDocument();
  });

  it("links the logo and brand name to the home page", async () => {
    await render(<Shell />);
    const home = screen.getByRole("link", { name: "Styrmin home" });
    expect(home).toHaveAttribute("href", "/");
    expect(within(home).getByText("Styrmin")).toBeInTheDocument();
  });

  it("keeps the logo linked to the home page when the sidebar is collapsed", async () => {
    const user = userEvent.setup();
    await render(<Shell />);

    await user.click(screen.getByText("Collapse"));

    const home = screen.getByRole("link", { name: "Styrmin home" });
    expect(home).toHaveAttribute("href", "/");
    expect(home).toHaveAttribute("title", "Styrmin home");
  });

  it("renders the theme toggle in the shared header, on every route", async () => {
    await render(<Shell role="ADMIN" />);

    const header = screen.getByTestId("app-header");
    expect(within(header).getByLabelText("Light mode")).toBeInTheDocument();
    expect(within(header).getByLabelText("Dark mode")).toBeInTheDocument();
  });

  it("hides labels and brand when sidebar is collapsed", async () => {
    const user = userEvent.setup();
    await render(<Shell />);

    await user.click(screen.getByText("Collapse"));

    expect(screen.queryByText("Environments")).toBeNull();
    expect(screen.queryByText("Drivers")).toBeNull();
    expect(screen.queryByText("Styrmin")).toBeNull();
  });

  it("links to the GraphQL sandbox in a new tab, for every role", async () => {
    await render(<Shell role="READ_ONLY" />);
    const link = screen.getByRole("link", { name: /GraphQL Sandbox/ });
    expect(link).toHaveAttribute("href", "/graphql");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAccessibleName("GraphQL Sandbox (opens in a new tab)");
  });

  it("keeps the GraphQL sandbox link when the sidebar is collapsed", async () => {
    const user = userEvent.setup();
    await render(<Shell />);

    await user.click(screen.getByText("Collapse"));

    const link = screen.getByRole("link", {
      name: "GraphQL Sandbox (opens in a new tab)",
    });
    expect(link).toHaveAttribute("href", "/graphql");
    expect(link).toHaveAttribute("title", "GraphQL Sandbox");
  });
});
