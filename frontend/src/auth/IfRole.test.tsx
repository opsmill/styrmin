import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  AuthContext,
  type AuthContextValue,
  type CurrentUser,
} from "./AuthProvider";
import { IfRole } from "./IfRole";

function makeUser(overrides: Partial<CurrentUser>): CurrentUser {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    username: "alice",
    displayName: "Alice",
    role: "READ_ONLY",
    effectiveRole: "READ_ONLY",
    active: true,
    ...overrides,
  };
}

function wrapWithAuth(value: AuthContextValue, ui: React.ReactNode) {
  return <AuthContext.Provider value={value}>{ui}</AuthContext.Provider>;
}

function makeAuthValue(currentUser: CurrentUser | null): AuthContextValue {
  return {
    currentUser,
    loading: false,
    refresh: async () => {},
    logout: async () => {},
  };
}

describe("IfRole", () => {
  it("renders children when effective role meets the minimum", () => {
    const auth = makeAuthValue(makeUser({ effectiveRole: "ADMIN" }));
    render(
      wrapWithAuth(
        auth,
        <IfRole minimum="ADMIN">
          <span>admin-content</span>
        </IfRole>,
      ),
    );
    expect(screen.getByText("admin-content")).toBeInTheDocument();
  });

  it("hides children when effective role is below the minimum", () => {
    const auth = makeAuthValue(makeUser({ effectiveRole: "READ_ONLY" }));
    render(
      wrapWithAuth(
        auth,
        <IfRole minimum="READ_WRITE">
          <span>write-content</span>
        </IfRole>,
      ),
    );
    expect(screen.queryByText("write-content")).not.toBeInTheDocument();
  });

  it("renders the fallback when effective role is below the minimum", () => {
    const auth = makeAuthValue(makeUser({ effectiveRole: "READ_WRITE" }));
    render(
      wrapWithAuth(
        auth,
        <IfRole minimum="ADMIN" fallback={<span>fallback-content</span>}>
          <span>admin-content</span>
        </IfRole>,
      ),
    );
    expect(screen.queryByText("admin-content")).not.toBeInTheDocument();
    expect(screen.getByText("fallback-content")).toBeInTheDocument();
  });

  it("renders nothing (no fallback) when unauthenticated", () => {
    const auth = makeAuthValue(null);
    const { container } = render(
      wrapWithAuth(
        auth,
        <IfRole minimum="READ_ONLY">
          <span>any</span>
        </IfRole>,
      ),
    );
    expect(container.textContent).toBe("");
  });

  it("renders ADMIN-minimum content for an admin-via-group user whose direct role is READ_ONLY", () => {
    // The user's direct role is READ_ONLY but they inherit ADMIN through a group,
    // so effectiveRole === "ADMIN". IfRole must use effectiveRole, not role.
    const auth = makeAuthValue(
      makeUser({ role: "READ_ONLY", effectiveRole: "ADMIN" }),
    );
    render(
      wrapWithAuth(
        auth,
        <IfRole minimum="ADMIN">
          <span>admin-content</span>
        </IfRole>,
      ),
    );
    expect(screen.getByText("admin-content")).toBeInTheDocument();
  });

  it("treats READ_WRITE as sufficient for READ_WRITE and READ_ONLY minimums", () => {
    const auth = makeAuthValue(makeUser({ effectiveRole: "READ_WRITE" }));
    render(
      wrapWithAuth(
        auth,
        <>
          <IfRole minimum="READ_ONLY">
            <span>ro-ok</span>
          </IfRole>
          <IfRole minimum="READ_WRITE">
            <span>rw-ok</span>
          </IfRole>
          <IfRole minimum="ADMIN">
            <span>admin-ok</span>
          </IfRole>
        </>,
      ),
    );
    expect(screen.getByText("ro-ok")).toBeInTheDocument();
    expect(screen.getByText("rw-ok")).toBeInTheDocument();
    expect(screen.queryByText("admin-ok")).not.toBeInTheDocument();
  });
});
