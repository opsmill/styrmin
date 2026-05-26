/**
 * Unit tests for the driver-detail Overview tab.
 *
 * Coverage:
 *   - Helm-chart tile surfaces chart name + version + repository.
 *   - Zero-components tile renders the empty-state label.
 *   - Zero-parameters tile renders the empty-state label.
 *   - SC-002: no `<pre>` element in any branch.
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { OverviewTab } from "@/pages/drivers/driver-detail/tabs/OverviewTab";
import type { DriverVersionDetail } from "@/pages/drivers/driver-detail/types";

function makeVersion(
  overrides: Partial<DriverVersionDetail>,
): DriverVersionDetail {
  const base: DriverVersionDetail = {
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
    parameters: [],
    componentConfigs: [],
    helmChart: {
      id: "chart-1",
      name: "nginx",
      version: "1.2.3",
      repository: "https://charts.example.com",
      valueTemplate: "{}",
    },
    actions: [],
  } as DriverVersionDetail;
  return { ...base, ...overrides } as DriverVersionDetail;
}

describe("OverviewTab", () => {
  it("renders the helm-chart tile with name + version + repository", () => {
    const { container } = render(
      <OverviewTab
        version={makeVersion({
          helmChart: {
            id: "chart-x",
            name: "nginx",
            version: "1.2.3",
            repository: "https://charts.example.com",
            valueTemplate: "{}",
          },
        })}
      />,
    );

    const tiles = screen.getByTestId("driver-overview-tiles");
    expect(within(tiles).getByText("nginx")).toBeInTheDocument();
    expect(within(tiles).getByText("1.2.3")).toBeInTheDocument();
    expect(
      within(tiles).getByText("https://charts.example.com"),
    ).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders the empty-state label for zero components", () => {
    const { container } = render(
      <OverviewTab version={makeVersion({ components: null })} />,
    );

    expect(screen.getByText("No components declared")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders the empty-state label for zero parameters with 0 required", () => {
    const { container } = render(
      <OverviewTab version={makeVersion({ parameters: [] })} />,
    );

    expect(screen.getByText("No parameters declared")).toBeInTheDocument();
    // "0 required" must NOT appear — that string is only rendered when at
    // least one parameter exists.
    expect(screen.queryByText(/0 required/)).not.toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("never renders <pre> with a fully-populated driver version (SC-002)", () => {
    const { container } = render(
      <OverviewTab
        version={makeVersion({
          components: {
            server: { identifier: { label: { role: "primary" } } },
            worker: { identifier: { label: { role: "secondary" } } },
          },
          parameters: [
            { name: "a", label: "A", kind: "string", default: null },
            {
              name: "b",
              label: "B",
              kind: "string",
              default: "x" as unknown as Record<string, unknown>,
            },
          ],
        })}
      />,
    );

    expect(container.querySelector("pre")).toBeNull();
    // Sanity-check the populated counts surfaced through the tiles.
    // "2" appears in both the components tile (2 components) and the
    // parameters tile (2 parameters); we just need both occurrences.
    expect(screen.getAllByText("2")).toHaveLength(2);
    expect(screen.getByText("1 required")).toBeInTheDocument();
  });

  it("filters non-object component entries from the count (parity with ComponentsTab)", () => {
    // `bad` has a string value — both ComponentsTab and the Overview tile
    // must skip it so they agree on the number.
    render(
      <OverviewTab
        version={makeVersion({
          components: {
            ok: { identifier: { label: { role: "primary" } } },
            bad: "not an object",
          } as unknown as DriverVersionDetail["components"],
        })}
      />,
    );

    expect(screen.getByText("1")).toBeInTheDocument();
    // "2" must NOT appear in the components tile — would indicate the old
    // unfiltered behaviour.
    expect(screen.queryByText("2")).not.toBeInTheDocument();
  });
});
