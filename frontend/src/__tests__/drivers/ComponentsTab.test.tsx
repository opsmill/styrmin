import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ComponentsTab } from "@/pages/drivers/driver-detail/tabs/ComponentsTab";
import type { DriverVersionDetail } from "@/pages/drivers/driver-detail/types";

function renderComponents(
  components: unknown,
  componentConfigs: DriverVersionDetail["componentConfigs"] = [],
) {
  return render(
    <ComponentsTab
      components={components as DriverVersionDetail["components"]}
      componentConfigs={componentConfigs}
    />,
  );
}

function componentConfig(
  name: string,
  container: string | null,
  replicaKeys: { replicas?: number; singleton?: boolean } = {},
): DriverVersionDetail["componentConfigs"][number] {
  return {
    id: `${name}-id`,
    name,
    config: {},
    container,
    replicas: replicaKeys.replicas ?? null,
    singleton: replicaKeys.singleton ?? false,
  };
}

describe("ComponentsTab", () => {
  it("renders the empty state when there are no components", () => {
    renderComponents(null);
    expect(screen.getByTestId("driver-components-empty")).toBeInTheDocument();
  });

  it("renders one card per component with its name", () => {
    renderComponents({
      server: { identifier: { label: { service: "web" } } },
      database: { identifier: { label: { service: "db" } } },
    });
    const rows = screen.getAllByTestId("driver-component-row");
    expect(rows).toHaveLength(2);
    expect(screen.getByText("server")).toBeInTheDocument();
    expect(screen.getByText("database")).toBeInTheDocument();
  });

  it("shows identifier labels, scalars and flattened nested objects as fields", () => {
    renderComponents({
      server: {
        identifier: { label: { "app.kubernetes.io/name": "web" } },
        cpu: 4,
        backup: { enabled: true, kind: "disk" },
      },
    });
    // identifier label
    expect(screen.getByText("app.kubernetes.io/name")).toBeInTheDocument();
    expect(screen.getByText("web")).toBeInTheDocument();
    // scalar
    expect(screen.getByText("cpu")).toBeInTheDocument();
    // nested object flattened to dotted keys
    expect(screen.getByText("backup.enabled")).toBeInTheDocument();
    expect(screen.getByText("backup.kind")).toBeInTheDocument();
    expect(screen.getByText("disk")).toBeInTheDocument();
    // no raw JSON dump
    const { baseElement } = render(<span />);
    expect(baseElement.querySelector("pre")).toBeNull();
  });

  it("renders declared-but-unset (null) fields as an em dash instead of dropping them", () => {
    renderComponents({
      server: {
        identifier: { label: { service: null } },
        chartVersion: null,
        cpu: 4,
      },
    });
    // both the top-level null and the null label selector keep their rows
    expect(screen.getByText("chartVersion")).toBeInTheDocument();
    expect(screen.getByText("service")).toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("shows each component's declared container", () => {
    renderComponents(
      {
        server: { identifier: { label: { service: "web" } } },
        worker: { identifier: { label: { service: "worker" } } },
      },
      [
        componentConfig("server", "simple-app"),
        componentConfig("worker", "celery"),
      ],
    );
    const [server, worker] = screen.getAllByTestId(
      "driver-component-container",
    );
    expect(server).toHaveTextContent("simple-app");
    expect(worker).toHaveTextContent("celery");
  });

  it("shows an explicit none-declared state for a component without a container", () => {
    renderComponents(
      {
        server: { identifier: { label: { service: "web" } }, container: null },
      },
      [componentConfig("server", null)],
    );
    const container = screen.getByTestId("driver-component-container");
    expect(container).toHaveTextContent("None declared");
    // the container is shown once, not repeated as a raw "container: —" field
    expect(screen.queryByText("—")).toBeNull();
  });

  it("shows each component's driver default replica count and singleton flag", () => {
    renderComponents(
      {
        server: { identifier: { label: { service: "web" } } },
        database: { identifier: { label: { service: "db" } } },
      },
      [
        componentConfig("server", "simple-app", { replicas: 2 }),
        componentConfig("database", "postgresql", { singleton: true }),
      ],
    );
    const [serverReplicas, databaseReplicas] = screen.getAllByTestId(
      "driver-component-replicas",
    );
    const [serverSingleton, databaseSingleton] = screen.getAllByTestId(
      "driver-component-singleton",
    );
    expect(serverReplicas).toHaveTextContent(/^Replicas2$/);
    expect(serverSingleton).toHaveTextContent(/^Singletonno$/);
    expect(databaseReplicas).toHaveTextContent(/^Replicasnot set$/);
    expect(databaseSingleton).toHaveTextContent(/^Singletonyes$/);
  });

  it("shows not set and no for a component without a component config", () => {
    renderComponents({ server: { identifier: { label: { service: "web" } } } });
    expect(screen.getByTestId("driver-component-replicas")).toHaveTextContent(
      "not set",
    );
    expect(screen.getByTestId("driver-component-singleton")).toHaveTextContent(
      "no",
    );
  });

  it("does not repeat replicas and singleton as raw declaration fields", () => {
    renderComponents(
      {
        server: {
          identifier: { label: { service: "web" } },
          replicas: 1,
          singleton: true,
          cpu: 4,
        },
      },
      [
        componentConfig("server", "simple-app", {
          replicas: 1,
          singleton: true,
        }),
      ],
    );
    expect(screen.getByText("cpu")).toBeInTheDocument();
    expect(screen.queryByText("replicas")).toBeNull();
    expect(screen.queryByText("singleton")).toBeNull();
    expect(screen.queryByText("true")).toBeNull();
  });
});
