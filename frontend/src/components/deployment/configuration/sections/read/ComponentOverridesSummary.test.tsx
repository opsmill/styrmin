/**
 * Read-only Component Overrides summary: per-component image overrides
 * (018-component-image-overrides, User Story 1 scenario 3).
 */
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import type { GetDeploymentQuery } from "@/generated/graphql";

import { ComponentOverridesSummary } from "./ComponentOverridesSummary";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;
type DeploymentComponent = Deployment["components"][number];
type ImageOverride = Deployment["componentImageOverrides"][number];

const COMPONENTS: DeploymentComponent[] = [
  { id: "c-server", name: "server", enabled: true, container: "server" },
  { id: "c-migrate", name: "migrate", enabled: true, container: null },
  { id: "c-worker", name: "worker", enabled: true, container: "worker" },
];

const TOKEN_REF = "registry.example/acme/app-patched:{{ app.version }}";
const TOKEN_RESOLVED = "registry.example/acme/app-patched:1.0.0";
const PINNED_REF = "registry.example/acme/app-patched:0.9.0";

function override(partial: Partial<ImageOverride>): ImageOverride {
  return {
    component: "server",
    reference: TOKEN_REF,
    resolvedReference: TOKEN_RESOLVED,
    isOrphaned: false,
    isApplicable: true,
    ...partial,
  };
}

function renderSummary(
  imageOverrides: ImageOverride[],
  deploymentConfig: Record<string, unknown> = {},
) {
  return render(
    <ComponentOverridesSummary
      deploymentConfig={deploymentConfig}
      environmentConfig={{}}
      clusterConfig={{}}
      components={COMPONENTS}
      imageOverrides={imageOverrides}
    />,
  );
}

function imageRow(component: string): HTMLElement {
  const rows = screen.getAllByTestId("component-image-override");
  const row = rows.find((r) => r.dataset.component === component);
  if (!row) throw new Error(`no image row for ${component}`);
  return row;
}

describe("ComponentOverridesSummary: image overrides", () => {
  it("shows the stored and resolved references with an applied badge", () => {
    renderSummary([override({})], {
      components: { server: { image: TOKEN_REF } },
    });

    const row = imageRow("server");
    expect(
      within(row).getByTestId("component-image-reference"),
    ).toHaveTextContent(TOKEN_REF);
    expect(
      within(row).getByTestId("component-image-resolved-reference"),
    ).toHaveTextContent(TOKEN_RESOLVED);
    expect(row).toHaveAttribute("data-applicable", "true");
    expect(
      within(row).getByTestId("component-image-applied-badge"),
    ).toHaveTextContent(/^applied$/);
  });

  it("shows a pinned reference once, since it resolves to itself", () => {
    renderSummary([
      override({ reference: PINNED_REF, resolvedReference: PINNED_REF }),
    ]);

    const row = imageRow("server");
    expect(
      within(row).getByTestId("component-image-reference"),
    ).toHaveTextContent(PINNED_REF);
    expect(
      within(row).queryByTestId("component-image-resolved-reference"),
    ).toBeNull();
    expect(row).toHaveAttribute("data-resolved-reference", PINNED_REF);
  });

  it("marks a non-applicable override as not applied", () => {
    renderSummary([
      override({
        component: "migrate",
        reference: PINNED_REF,
        resolvedReference: PINNED_REF,
        isApplicable: false,
      }),
    ]);

    const row = imageRow("migrate");
    expect(row).toHaveAttribute("data-applicable", "false");
    expect(
      within(row).getByTestId("component-image-applied-badge"),
    ).toHaveTextContent(/^not applied$/);
  });

  it("renders image rows only for components that carry an override", () => {
    renderSummary([override({})], {
      components: { server: { image: TOKEN_REF } },
    });

    expect(screen.getAllByTestId("component-image-override")).toHaveLength(1);
    const workerRow = screen
      .getAllByTestId("component-override-row")
      .find((r) => r.dataset.component === "worker");
    expect(workerRow).toHaveTextContent("no override");
  });

  it("lists the image in the one-line override summary", () => {
    renderSummary([override({})], {
      components: {
        server: { env_vars: { LOG_LEVEL: "debug" }, image: TOKEN_REF },
      },
    });

    const serverRow = screen
      .getAllByTestId("component-override-row")
      .find((r) => r.dataset.component === "server");
    expect(serverRow).toHaveTextContent("env_vars: 1 key · image");
  });

  it("shows an orphaned image override as not applied", () => {
    renderSummary([
      override({}),
      override({
        component: "legacy",
        reference: PINNED_REF,
        resolvedReference: PINNED_REF,
        isOrphaned: true,
        isApplicable: false,
      }),
    ]);

    const orphanRow = screen.getByTestId("component-override-orphan-row");
    expect(orphanRow).toHaveAttribute("data-component", "legacy");
    expect(orphanRow).toHaveTextContent("no longer declared by driver");
    const row = imageRow("legacy");
    expect(orphanRow).toContainElement(row);
    expect(
      within(row).getByTestId("component-image-reference"),
    ).toHaveTextContent(PINNED_REF);
    expect(
      within(row).getByTestId("component-image-applied-badge"),
    ).toHaveTextContent(/^not applied$/);
  });

  it("shows orphaned image overrides when the driver declares no components", () => {
    render(
      <ComponentOverridesSummary
        deploymentConfig={{}}
        environmentConfig={{}}
        clusterConfig={{}}
        components={[]}
        imageOverrides={[
          override({
            component: "legacy",
            isOrphaned: true,
            isApplicable: false,
          }),
        ]}
      />,
    );

    expect(screen.queryByText("driver declares no components")).toBeNull();
    expect(imageRow("legacy")).toHaveAttribute("data-applicable", "false");
  });

  it("tolerates a missing override list", () => {
    render(
      <ComponentOverridesSummary
        deploymentConfig={{}}
        environmentConfig={{}}
        clusterConfig={{}}
        components={COMPONENTS}
      />,
    );
    expect(screen.queryByTestId("component-image-override")).toBeNull();
  });
});
