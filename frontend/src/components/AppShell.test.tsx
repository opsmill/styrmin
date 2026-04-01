import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, userEvent } from "@/test/utils";
import { AppShell } from "./AppShell";

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
    await render(<AppShell />);
    expect(screen.getByText("Environments")).toBeInTheDocument();
    expect(screen.getByText("Drivers")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders the Styrmin brand name", async () => {
    await render(<AppShell />);
    expect(screen.getByText("Styrmin")).toBeInTheDocument();
  });

  it("hides labels and brand when sidebar is collapsed", async () => {
    const user = userEvent.setup();
    await render(<AppShell />);

    await user.click(screen.getByText("Collapse"));

    expect(screen.queryByText("Environments")).toBeNull();
    expect(screen.queryByText("Drivers")).toBeNull();
    expect(screen.queryByText("Styrmin")).toBeNull();
  });
});
