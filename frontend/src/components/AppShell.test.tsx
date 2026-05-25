import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
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
    expect(screen.getByText("Backup Storage")).toBeInTheDocument();
  });

  it("renders Clusters in the bottom nav regardless of role", async () => {
    await render(<Shell />);
    expect(screen.getByText("Clusters")).toBeInTheDocument();
  });

  it("hides Settings for non-admin users", async () => {
    await render(<Shell role="READ_WRITE" />);
    expect(screen.queryByText("Settings")).toBeNull();
  });

  it("hides Settings for unauthenticated context", async () => {
    await render(<Shell />);
    expect(screen.queryByText("Settings")).toBeNull();
  });

  it("shows Settings for ADMIN users, immediately after Clusters", async () => {
    await render(<Shell role="ADMIN" />);
    const clusters = screen.getByText("Clusters");
    const settings = screen.getByText("Settings");
    expect(settings).toBeInTheDocument();
    // DOM order: Clusters comes before Settings in the bottom group.
    expect(
      clusters.compareDocumentPosition(settings) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("renders the Styrmin brand name", async () => {
    await render(<Shell />);
    expect(screen.getByText("Styrmin")).toBeInTheDocument();
  });

  it("hides labels and brand when sidebar is collapsed", async () => {
    const user = userEvent.setup();
    await render(<Shell />);

    await user.click(screen.getByText("Collapse"));

    expect(screen.queryByText("Environments")).toBeNull();
    expect(screen.queryByText("Drivers")).toBeNull();
    expect(screen.queryByText("Styrmin")).toBeNull();
  });
});
