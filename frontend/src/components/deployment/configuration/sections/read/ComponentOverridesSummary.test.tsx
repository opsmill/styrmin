/**
 * Read-only Component Overrides summary: per-component image overrides
 * (018-component-image-overrides, User Story 1 scenario 3), `command`/`args`
 * overrides (022-post-render-container-overrides) and replica counts
 * (023-per-component-replicas, User Story 3).
 */
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import type { GetDeploymentQuery } from "@/generated/graphql";

import { ComponentOverridesSummary } from "./ComponentOverridesSummary";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;
type DeploymentComponent = Deployment["components"][number];
type ImageOverride = Deployment["componentImageOverrides"][number];
type ContainerOverride = Deployment["componentContainerOverrides"][number];
type ComponentReplicas = Deployment["componentReplicas"][number];

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

function containerOverride(
  partial: Partial<ContainerOverride>,
): ContainerOverride {
  return {
    component: "server",
    command: null,
    args: null,
    isOrphaned: false,
    isApplicable: true,
    ...partial,
  };
}

function renderContainerSummary(
  containerOverrides: ContainerOverride[],
  deploymentConfig: Record<string, unknown> = {},
) {
  return render(
    <ComponentOverridesSummary
      deploymentConfig={deploymentConfig}
      environmentConfig={{}}
      clusterConfig={{}}
      components={COMPONENTS}
      containerOverrides={containerOverrides}
    />,
  );
}

function containerLine(component: string, field: string): HTMLElement {
  const line = screen
    .getAllByTestId("component-container-override")
    .find(
      (r) => r.dataset.component === component && r.dataset.field === field,
    );
  if (!line) throw new Error(`no ${field} line for ${component}`);
  return line;
}

describe("ComponentOverridesSummary: command and args overrides", () => {
  it("shows each list as JSON with an applied badge", () => {
    renderContainerSummary(
      [containerOverride({ command: ["a b"], args: ["a", "", "b"] })],
      { components: { server: { command: ["a b"], args: ["a", "", "b"] } } },
    );

    const command = containerLine("server", "command");
    expect(
      within(command).getByTestId("component-container-override-value"),
    ).toHaveTextContent('["a b"]');
    expect(
      within(command).getByTestId("component-container-override-applied-badge"),
    ).toHaveTextContent(/^applied$/);
    expect(
      within(containerLine("server", "args")).getByTestId(
        "component-container-override-value",
      ),
    ).toHaveTextContent('["a","","b"]');
    const serverRow = screen
      .getAllByTestId("component-override-row")
      .find((r) => r.dataset.component === "server");
    expect(serverRow).toHaveTextContent("command · args");
  });

  it("marks values on a component without a container not applied", () => {
    renderContainerSummary(
      [
        containerOverride({
          component: "migrate",
          args: ["--all"],
          isApplicable: false,
        }),
      ],
      { components: { migrate: { args: ["--all"] } } },
    );

    const line = containerLine("migrate", "args");
    expect(line).toHaveAttribute("data-applicable", "false");
    expect(
      within(line).getByTestId("component-container-override-applied-badge"),
    ).toHaveTextContent(/^not applied$/);
    expect(
      screen
        .getAllByTestId("component-container-override")
        .filter((r) => r.dataset.field === "command"),
    ).toHaveLength(0);
  });

  it("shows an orphaned command as not applied", () => {
    renderContainerSummary(
      [
        containerOverride({
          component: "legacy",
          command: ["/bin/legacy"],
          isOrphaned: true,
          isApplicable: false,
        }),
      ],
      { components: { legacy: { command: ["/bin/legacy"] } } },
    );

    const orphanRow = screen.getByTestId("component-override-orphan-row");
    expect(orphanRow).toHaveAttribute("data-component", "legacy");
    expect(orphanRow).toHaveTextContent(
      "no longer declared by driver · command",
    );
    expect(orphanRow).toContainElement(containerLine("legacy", "command"));
  });

  it("shows an orphaned block that stores only env vars", () => {
    renderContainerSummary([], {
      components: { legacy: { env_vars: { LOG_LEVEL: "debug" } } },
    });

    const orphanRow = screen.getByTestId("component-override-orphan-row");
    expect(orphanRow).toHaveAttribute("data-component", "legacy");
    expect(orphanRow).toHaveTextContent(
      "no longer declared by driver · env_vars: 1 key",
    );
  });
});

function replicaRow(partial: Partial<ComponentReplicas>): ComponentReplicas {
  return {
    component: "server",
    count: null,
    source: "CHART",
    override: null,
    singleton: false,
    isOrphaned: false,
    isApplicable: true,
    ...partial,
  };
}

const REPLICA_COMPONENTS: DeploymentComponent[] = [
  { id: "c-database", name: "database", enabled: true, container: "db" },
  { id: "c-migrate", name: "migrate", enabled: true, container: null },
  { id: "c-server", name: "server", enabled: true, container: "server" },
  { id: "c-worker", name: "worker", enabled: false, container: "worker" },
];

function renderReplicaSummary(
  replicas: ComponentReplicas[],
  deploymentConfig: Record<string, unknown> = {},
) {
  return render(
    <ComponentOverridesSummary
      deploymentConfig={deploymentConfig}
      environmentConfig={{}}
      clusterConfig={{}}
      components={REPLICA_COMPONENTS}
      replicas={replicas}
    />,
  );
}

function replicaLine(component: string): HTMLElement {
  const line = screen
    .getAllByTestId("component-replicas")
    .find((r) => r.dataset.component === component);
  if (!line) throw new Error(`no replicas line for ${component}`);
  return line;
}

describe("ComponentOverridesSummary: replica counts", () => {
  it("shows the count and its source on every component", () => {
    renderReplicaSummary(
      [
        replicaRow({
          component: "database",
          count: 1,
          source: "DRIVER_DEFAULT",
          singleton: true,
        }),
        replicaRow({ component: "migrate" }),
        replicaRow({
          component: "server",
          count: 3,
          source: "OVERRIDE",
          override: 3,
        }),
        replicaRow({ component: "worker", count: 2, source: "DRIVER_DEFAULT" }),
      ],
      { components: { server: { replicas: 3 } } },
    );

    const value = (component: string) =>
      within(replicaLine(component)).getByTestId("component-replicas-value");
    expect(value("server")).toHaveTextContent(/^3 \(override\)$/);
    expect(value("worker")).toHaveTextContent(/^2 \(driver default\)$/);
    expect(value("migrate")).toHaveTextContent(/^set by the chart$/);
    expect(value("database")).toHaveTextContent(
      /^1 \(driver default, singleton\)$/,
    );
    expect(replicaLine("server")).toHaveAttribute("data-source", "OVERRIDE");
    expect(replicaLine("server")).toHaveTextContent(/^replicas/);
    expect(
      within(replicaLine("server")).getByTestId(
        "component-replicas-applied-badge",
      ),
    ).toHaveTextContent(/^applied$/);
    // No stored override, so nothing to mark applied or not.
    expect(
      within(replicaLine("worker")).queryByTestId(
        "component-replicas-applied-badge",
      ),
    ).toBeNull();
    const serverRow = screen
      .getAllByTestId("component-override-row")
      .find((r) => r.dataset.component === "server");
    expect(serverRow).toHaveTextContent("replicas");
    expect(serverRow).not.toHaveTextContent("override (empty)");
  });

  it("marks a stored override that does not apply as not applied", () => {
    renderReplicaSummary([
      replicaRow({
        component: "database",
        count: 1,
        source: "DRIVER_DEFAULT",
        override: 3,
        singleton: true,
        isApplicable: false,
      }),
    ]);

    const line = replicaLine("database");
    expect(line).toHaveAttribute("data-applicable", "false");
    expect(
      within(line).getByTestId("component-replicas-value"),
    ).toHaveTextContent(/^1 \(driver default, singleton\)$/);
    expect(line).toHaveTextContent("override 3");
    expect(
      within(line).getByTestId("component-replicas-applied-badge"),
    ).toHaveTextContent(/^not applied$/);
  });

  it("shows a stopped component at 0 pods next to the count it returns to", () => {
    renderReplicaSummary([
      replicaRow({
        component: "server",
        count: 3,
        source: "OVERRIDE",
        override: 3,
      }),
      replicaRow({
        component: "worker",
        count: 3,
        source: "OVERRIDE",
        override: 3,
      }),
    ]);

    const worker = replicaLine("worker");
    expect(worker).toHaveAttribute("data-stopped", "true");
    expect(
      within(worker).getByTestId("component-replicas-value"),
    ).toHaveTextContent(/^3 \(override\)$/);
    expect(
      within(worker).getByTestId("component-replicas-stopped"),
    ).toHaveTextContent(/^stopped: 0 pods$/);
    expect(replicaLine("server")).toHaveAttribute("data-stopped", "false");
    expect(
      within(replicaLine("server")).queryByTestId("component-replicas-stopped"),
    ).toBeNull();
  });

  it("shows an orphaned replica override in its own row as not applied", () => {
    renderReplicaSummary(
      [
        replicaRow({ component: "server" }),
        replicaRow({
          component: "legacy",
          override: 3,
          isOrphaned: true,
          isApplicable: false,
        }),
      ],
      { components: { legacy: { replicas: 3 } } },
    );

    const orphanRow = screen.getByTestId("component-override-orphan-row");
    expect(orphanRow).toHaveAttribute("data-component", "legacy");
    expect(orphanRow).toHaveTextContent(
      "no longer declared by driver · replicas",
    );
    const line = replicaLine("legacy");
    expect(orphanRow).toContainElement(line);
    expect(
      within(line).getByTestId("component-replicas-value"),
    ).toHaveTextContent(/^3 \(override\)$/);
    expect(
      within(line).getByTestId("component-replicas-applied-badge"),
    ).toHaveTextContent(/^not applied$/);
    expect(line).toHaveAttribute("data-stopped", "false");
  });

  it("shows an orphaned replica override that only the read field reports", () => {
    renderReplicaSummary([
      replicaRow({
        component: "legacy",
        override: 2,
        isOrphaned: true,
        isApplicable: false,
      }),
    ]);

    expect(screen.getByTestId("component-override-orphan-row")).toHaveAttribute(
      "data-component",
      "legacy",
    );
    expect(replicaLine("legacy")).toHaveAttribute("data-applicable", "false");
  });
});
