/**
 * Upgrade-dialog warning for pinned image overrides
 * (018-component-image-overrides, User Story 2, FR-008).
 */
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import type { GetDeploymentQuery } from "@/generated/graphql";

import { PinnedImageOverridesNotice } from "./PinnedImageOverridesNotice";

type ImageOverride = NonNullable<
  GetDeploymentQuery["deployment"]
>["componentImageOverrides"][number];

const PINNED_REF = "registry.example/acme/app-patched:1.0.0";
const TOKEN_REF = "registry.example/acme/app-patched:{{ app.version }}";

function override(partial: Partial<ImageOverride>): ImageOverride {
  return {
    component: "server",
    reference: PINNED_REF,
    resolvedReference: PINNED_REF,
    isOrphaned: false,
    isApplicable: true,
    ...partial,
  };
}

describe("PinnedImageOverridesNotice", () => {
  it("lists applicable, token-free overrides with their references", () => {
    render(
      <PinnedImageOverridesNotice
        overrides={[
          override({ component: "server" }),
          override({
            component: "worker",
            reference: TOKEN_REF,
            resolvedReference: "registry.example/acme/app-patched:2.0.0",
          }),
          override({ component: "migrate", isApplicable: false }),
          override({
            component: "api",
            reference: "registry.example/acme/api:3.1.0",
            resolvedReference: "registry.example/acme/api:3.1.0",
          }),
        ]}
      />,
    );

    const notice = screen.getByRole("alert", {
      name: "Pinned image overrides",
    });
    expect(notice).toHaveAttribute(
      "data-testid",
      "pinned-image-overrides-notice",
    );
    expect(notice).toHaveTextContent(
      "These components keep their pinned image after the upgrade:",
    );

    const items = within(notice).getAllByTestId("pinned-image-override");
    expect(items.map((item) => item.dataset.component)).toEqual([
      "api",
      "server",
    ]);
    expect(items.map((item) => item.textContent)).toEqual([
      "api (registry.example/acme/api:3.1.0)",
      `server (${PINNED_REF})`,
    ]);
    expect(items[1]).toHaveAttribute("data-reference", PINNED_REF);
  });

  it("renders nothing when every override has the token or is not applicable", () => {
    const { container } = render(
      <PinnedImageOverridesNotice
        overrides={[
          override({ component: "server", reference: TOKEN_REF }),
          override({
            component: "worker",
            reference: "registry.example/acme/app:{{app.version}}-worker",
          }),
          override({ component: "migrate", isApplicable: false }),
          override({
            component: "ghost",
            isOrphaned: true,
            isApplicable: false,
          }),
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(
      screen.queryByTestId("pinned-image-overrides-notice"),
    ).not.toBeInTheDocument();
  });

  it("renders nothing without overrides", () => {
    const { container } = render(<PinnedImageOverridesNotice overrides={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
