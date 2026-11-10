import { describe, expect, it } from "vitest";

import { ingressClassError, servicesWithInvalidClass } from "./ingress-class";

describe("ingressClassError", () => {
  it.each([
    "traefik",
    "nginx",
    "tailscale",
    "prod-nginx",
    "cluster-traefik",
    "a",
    "k8s.io-ingress-nginx",
    "a".repeat(63),
    `${"a".repeat(63)}.${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(61)}`,
    "",
    null,
    undefined,
  ])("accepts %j", (value) => {
    expect(ingressClassError(value)).toBeNull();
  });

  it.each([
    "traefik\n",
    "\ntraefik",
    "tra\nefik",
    "traefik\r",
    "tra\tefik",
    "my class",
    "traefik ",
    " traefik",
    "traefik\u0000",
    "tra efik",
    "Traefik",
    "my_class",
    "a/b",
    "a:b",
    'a"b',
    "-traefik",
    "traefik-",
    ".traefik",
    "traefik.",
    "a..b",
    "a-.b",
    `${"a".repeat(63)}.${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(62)}`,
  ])("rejects %j with a message that names the rule", (value) => {
    expect(ingressClassError(value)).toMatch(/Kubernetes object name/);
  });
});

describe("ingressClassError message", () => {
  it("says that each dot-separated label starts and ends with a letter or a digit", () => {
    expect(ingressClassError("a.-b")).toMatch(
      /each dot-separated label starts and ends with a letter or a digit/,
    );
  });
});

describe("servicesWithInvalidClass", () => {
  it("lists the services whose ingress class is invalid", () => {
    expect(
      servicesWithInvalidClass([
        { name: "web", ingressClass: "Bad_Class" },
        { name: "api", ingressClass: "traefik" },
        { name: "task-manager", ingressClass: "a\nb", fqdnSuffix: "ok.com" },
        { name: "empty", ingressClass: "" },
      ]),
    ).toEqual(["web", "task-manager"]);
  });

  it("returns nothing without rows", () => {
    expect(servicesWithInvalidClass(undefined)).toEqual([]);
    expect(servicesWithInvalidClass(null)).toEqual([]);
  });
});
