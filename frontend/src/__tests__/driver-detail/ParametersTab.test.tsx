/**
 * Unit tests for the driver-detail Parameters tab.
 *
 * Coverage:
 *   - REQUIRED indicator when `default === null` (FR-011).
 *   - Optional indicator when a non-null default is present.
 *   - Object defaults render as a JSON.stringify-formatted string (current
 *     behaviour) WITHOUT introducing a `<pre>` JSON dump.
 *   - SC-002: no `<pre>` element in the rendered output under any branch.
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { ParametersTab } from "@/pages/drivers/driver-detail/tabs/ParametersTab";
import type { DriverVersionDetail } from "@/pages/drivers/driver-detail/types";

function makeVersion(
  parameters: DriverVersionDetail["parameters"],
): DriverVersionDetail {
  return {
    id: "v-1",
    version: "1.0.0",
    supportedVersions: "*",
    sourceType: "git",
    sourceRepository: "https://github.com/example/repo.git",
    sourceBranch: "main",
    sourcePath: null,
    sourceCommitSha: null,
    contentHash: null,
    createdOn: "2026-01-01T00:00:00Z",
    components: null,
    parameters,
    componentConfigs: [],
    helmChart: {
      id: "chart-1",
      name: "chart",
      version: "0.1.0",
      repository: "https://charts.example.com",
      valueTemplate: "{}",
    },
    actions: [],
  } as DriverVersionDetail;
}

describe("ParametersTab", () => {
  it("renders the empty state when no parameters are declared (FR-017)", () => {
    const { container } = render(<ParametersTab version={makeVersion([])} />);
    expect(screen.getByTestId("driver-parameters-empty")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("marks a parameter REQUIRED when default is null (FR-011)", () => {
    const { container } = render(
      <ParametersTab
        version={makeVersion([
          {
            name: "host",
            label: "Host",
            kind: "string",
            default: null,
          },
        ])}
      />,
    );

    const row = screen.getByTestId("driver-parameter-row");
    expect(row.getAttribute("data-parameter-name")).toBe("host");
    expect(within(row).getByText("Required")).toBeInTheDocument();
    expect(within(row).queryByText("Optional")).not.toBeInTheDocument();
    // Default cell renders the em-dash placeholder, not "null".
    expect(within(row).getByText("—")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("marks a parameter Optional when a non-null default is present", () => {
    const { container } = render(
      <ParametersTab
        version={makeVersion([
          {
            name: "port",
            label: "Port",
            kind: "string",
            // JSON scalar is typed as `Record<string, unknown>` in the
            // generated bindings; cast through unknown to feed it the
            // string-default that the backend actually allows at runtime.
            default: "x" as unknown as Record<string, unknown>,
          },
        ])}
      />,
    );

    const row = screen.getByTestId("driver-parameter-row");
    expect(row.getAttribute("data-parameter-name")).toBe("port");
    expect(within(row).getByText("Optional")).toBeInTheDocument();
    expect(within(row).queryByText("Required")).not.toBeInTheDocument();
    expect(within(row).getByText("x")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders an object default as a JSON.stringify-formatted string (no <pre>)", () => {
    const { container } = render(
      <ParametersTab
        version={makeVersion([
          {
            name: "config",
            label: "Config",
            kind: "object",
            default: { nested: 1 },
          },
        ])}
      />,
    );

    const row = screen.getByTestId("driver-parameter-row");
    expect(row.getAttribute("data-parameter-name")).toBe("config");
    // Object default has a non-null `default`, so it's Optional.
    expect(within(row).getByText("Optional")).toBeInTheDocument();
    // Formatted as JSON.stringify, NOT as a multi-line <pre> block.
    expect(within(row).getByText('{"nested":1}')).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("never renders <pre> across mixed parameter shapes (SC-002)", () => {
    const { container } = render(
      <ParametersTab
        version={makeVersion([
          { name: "a", label: "A", kind: "string", default: null },
          {
            name: "b",
            label: "B",
            kind: "string",
            default: "x" as unknown as Record<string, unknown>,
          },
          {
            name: "c",
            label: "C",
            kind: "object",
            default: { nested: 1 },
          },
        ])}
      />,
    );

    expect(screen.getAllByTestId("driver-parameter-row")).toHaveLength(3);
    expect(container.querySelector("pre")).toBeNull();
  });
});
