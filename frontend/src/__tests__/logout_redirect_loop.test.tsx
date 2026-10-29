/**
 * Logout from the Environments page must land on /login and stop.
 *
 * Mounts the real <App /> (real AuthProvider, router and query client) over a
 * fake GraphQL server. After Logout the fake server answers like the real one:
 * `currentUser` is null, `environments` is still allow-listed, and every other
 * root field is rejected with code UNAUTHENTICATED.
 *
 * Uses the plain `render`, not `@/test/utils`: <App /> brings its own router,
 * and the wrapper there would add a second one.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "@/App";

const ADMIN = {
  id: "u-admin",
  username: "admin",
  displayName: "admin",
  role: "ADMIN",
  effectiveRole: "ADMIN",
  active: true,
};

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function installFakeServer() {
  const state = { signedIn: true, calls: [] as string[] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: unknown, init?: RequestInit) => {
      const query = JSON.parse(String(init?.body)).query as string;
      const op = /(?:query|mutation)\s+(\w+)/.exec(query)?.[1] ?? "?";
      state.calls.push(op);
      // A real response arrives in a later task, never in the same one.
      await new Promise((resolve) => setTimeout(resolve, 1));
      switch (op) {
        case "CurrentUser":
          return json({ data: { currentUser: state.signedIn ? ADMIN : null } });
        case "Logout":
          state.signedIn = false;
          return json({ data: { logout: true } });
        case "ListEnvironments":
          return json({ data: { environments: [] } });
        default:
          if (state.signedIn) return json({ data: { clusters: [] } });
          return json({
            data: null,
            errors: [
              {
                message: "Authentication is required",
                extensions: { code: "UNAUTHENTICATED" },
              },
            ],
          });
      }
    }),
  );
  return state;
}

describe("logout from the Environments page", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the sign-in page and stops sending requests", async () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
      clear: () => store.clear(),
    });
    const server = installFakeServer();
    render(<App />);

    await screen.findByRole("heading", { name: "Environments" });

    const ue = userEvent.setup();
    await ue.click(screen.getByTestId("header-user-menu-trigger"));
    const callsBeforeLogout = server.calls.length;
    await ue.click(await screen.findByTestId("header-user-menu-logout"));

    await waitFor(() => {
      expect(window.location.pathname).toBe("/login");
      expect(
        screen.getByRole("heading", { name: "Sign in to Styrmin" }),
      ).toBeInTheDocument();
    });

    // Give a redirect loop time to show itself, then count what was sent.
    await new Promise((resolve) => setTimeout(resolve, 500));
    const afterLogout = server.calls.slice(callsBeforeLogout);
    expect(window.location.pathname).toBe("/login");
    expect(afterLogout.length).toBeLessThan(10);
  });
});
