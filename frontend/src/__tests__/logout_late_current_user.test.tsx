/**
 * A current-user response that arrives after Logout must not sign the user
 * back in.
 *
 * Mounts the real <App /> (real AuthProvider, router and query client) over a
 * fake GraphQL server. The user saves a new display name, which re-fetches the
 * current user. Before that response arrives the user selects Logout. The
 * fake server answers the re-fetch with the signed-in user, as the real server
 * does for a request it received before the Logout, and the test delivers that
 * response after Logout has finished. Back must then land on the sign-in page,
 * not on the profile page.
 *
 * Uses the plain `render`, not `@/test/utils`: <App /> brings its own router.
 * The router is a module-level singleton, so each case loads <App /> into a
 * fresh module registry and does not inherit the previous case's location.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const ADMIN = {
  id: "u-admin",
  username: "admin",
  displayName: "admin",
  role: "ADMIN",
  effectiveRole: "ADMIN",
  active: true,
  groups: [],
};

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function installFakeServer() {
  const state = {
    signedIn: true,
    displayName: ADMIN.displayName,
    // When set, the next CurrentUser response is built at once but delivered
    // only when `releaseHeld` is called.
    holdNextCurrentUser: false,
    heldCurrentUser: false,
    // Set once the held response has been handed back to the caller.
    heldDelivered: false,
    releaseHeld: (): void => undefined,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: unknown, init?: RequestInit) => {
      const query = JSON.parse(String(init?.body)).query as string;
      const op = /(?:query|mutation)\s+(\w+)/.exec(query)?.[1] ?? "?";
      await new Promise((resolve) => setTimeout(resolve, 1));
      switch (op) {
        case "CurrentUser": {
          const response = json({
            data: {
              currentUser: state.signedIn
                ? { ...ADMIN, displayName: state.displayName }
                : null,
            },
          });
          if (state.holdNextCurrentUser) {
            state.holdNextCurrentUser = false;
            state.heldCurrentUser = true;
            await new Promise<void>((resolve) => {
              state.releaseHeld = resolve;
            });
            state.heldDelivered = true;
          }
          return response;
        }
        case "UpdateUser":
          state.displayName = JSON.parse(String(init?.body)).variables.input
            .displayName as string;
          return json({
            data: {
              updateUser: { ...ADMIN, displayName: state.displayName },
            },
          });
        case "Logout":
          state.signedIn = false;
          return json({ data: { logout: true } });
        default:
          return json({ data: {} });
      }
    }),
  );
  return state;
}

describe("a current-user response that arrives after Logout", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it.each([
    { holdRefetch: true, name: "arrives after Logout" },
    { holdRefetch: false, name: "arrived before Logout" },
  ])(
    "shows the sign-in page on Back when the current-user response $name",
    async ({ holdRefetch }) => {
      const store = new Map<string, string>();
      vi.stubGlobal("localStorage", {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
        clear: () => store.clear(),
      });
      vi.resetModules();
      const { default: App } = await import("@/App");
      const server = installFakeServer();
      window.history.pushState({}, "", "/profile");
      render(<App />);

      const ue = userEvent.setup();
      const nameInput = await screen.findByTestId("profile-display-name");

      // Save a new display name. The save re-fetches the current user, and the
      // server's answer to that re-fetch is held back.
      server.holdNextCurrentUser = holdRefetch;
      await ue.clear(nameInput);
      await ue.type(nameInput, "Admin Renamed");
      await ue.click(screen.getByRole("button", { name: "Save display name" }));
      if (holdRefetch) {
        await waitFor(() => expect(server.heldCurrentUser).toBe(true));
      }

      // Logout before that response arrives.
      await ue.click(screen.getByTestId("header-user-menu-trigger"));
      await ue.click(await screen.findByTestId("header-user-menu-logout"));
      await waitFor(() => {
        expect(window.location.pathname).toBe("/login");
        expect(
          screen.getByRole("heading", { name: "Sign in to Styrmin" }),
        ).toBeInTheDocument();
      });

      // The held response now arrives, after Logout has finished. Wait until
      // the fake server has handed it back, then let React Query process it.
      if (holdRefetch) {
        server.releaseHeld();
        await waitFor(() => expect(server.heldDelivered).toBe(true));
        await act(async () => {
          for (let tick = 0; tick < 5; tick += 1) {
            await new Promise((resolve) => setTimeout(resolve, 10));
          }
        });
      }

      // Back to the profile page. The route guard sends a signed-out user to
      // /login with `next=/profile`; that redirect is the positive sign that
      // Back was handled and refused. If the profile page opens instead, this
      // wait times out and the test fails.
      window.history.back();
      await waitFor(() => {
        expect(window.location.pathname).toBe("/login");
        expect(window.location.search).toBe("?next=%2Fprofile");
      });
      expect(
        screen.queryByTestId("profile-display-name"),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Sign in to Styrmin" }),
      ).toBeInTheDocument();
    },
  );
});
