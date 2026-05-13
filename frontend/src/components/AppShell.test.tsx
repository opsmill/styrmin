import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
import { AppShell } from "./AppShell";
import { AuthContext, type AuthContextValue } from "@/auth/AuthProvider";

const noopAuth: AuthContextValue = {
  currentUser: null,
  loading: false,
  refresh: () => Promise.resolve(),
  logout: () => Promise.resolve(),
};

function Shell() {
  return (
    <AuthContext.Provider value={noopAuth}>
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

  it("renders navigation links", async () => {
    await render(<Shell />);
    expect(screen.getByText("Environments")).toBeInTheDocument();
    expect(screen.getByText("Drivers")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
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
