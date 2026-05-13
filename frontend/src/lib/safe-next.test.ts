import { describe, it, expect } from "vitest";
import { safeNext } from "./safe-next";

describe("safeNext", () => {
  it("accepts a plain same-origin absolute path", () => {
    expect(safeNext("/users")).toBe("/users");
    expect(safeNext("/users/abc-123")).toBe("/users/abc-123");
    expect(safeNext("/deployments/x/details")).toBe("/deployments/x/details");
  });

  it("accepts pathnames that include a search/hash component", () => {
    expect(safeNext("/users?foo=bar")).toBe("/users?foo=bar");
    expect(safeNext("/users#section")).toBe("/users#section");
  });

  it("rejects protocol-relative URLs (//evil.com)", () => {
    expect(safeNext("//evil.com")).toBeNull();
    expect(safeNext("//evil.com/path")).toBeNull();
  });

  it("rejects back-slash variants (/\\evil.com)", () => {
    expect(safeNext("/\\evil.com")).toBeNull();
  });

  it("rejects absolute URLs of any scheme", () => {
    expect(safeNext("http://evil.com")).toBeNull();
    expect(safeNext("https://evil.com/path")).toBeNull();
    expect(safeNext("javascript:alert(1)")).toBeNull();
    expect(safeNext("data:text/html,<script>")).toBeNull();
    expect(safeNext("ftp://elsewhere")).toBeNull();
  });

  it("rejects relative paths (no leading /)", () => {
    expect(safeNext("users")).toBeNull();
    expect(safeNext("./users")).toBeNull();
    expect(safeNext("../etc/passwd")).toBeNull();
  });

  it("rejects the bare /login path and /login?…", () => {
    expect(safeNext("/login")).toBeNull();
    expect(safeNext("/login?next=/")).toBeNull();
  });

  it("rejects empty / whitespace / non-string", () => {
    expect(safeNext("")).toBeNull();
    expect(safeNext(" ")).toBeNull();
    expect(safeNext("\n")).toBeNull();
    expect(safeNext("/with space")).toBeNull();
    expect(safeNext(undefined)).toBeNull();
    expect(safeNext(null)).toBeNull();
    expect(safeNext(42)).toBeNull();
  });

  it("rejects strings with control characters", () => {
    expect(safeNext("/path\x00null")).toBeNull();
    expect(safeNext("/path\nnewline")).toBeNull();
  });
});
