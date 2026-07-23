import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ComponentsTab } from "@/pages/drivers/driver-detail/tabs/ComponentsTab";
import type { DriverVersionDetail } from "@/pages/drivers/driver-detail/types";

function renderComponents(components: unknown) {
  return render(
    <ComponentsTab
      components={components as DriverVersionDetail["components"]}
    />,
  );
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
});
