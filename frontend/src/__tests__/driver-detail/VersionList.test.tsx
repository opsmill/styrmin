/**
 * Unit tests for the driver-detail left-rail `VersionList` (T020).
 *
 * Covers:
 *   - newest-first ordering by `createdOn` (FR-001)
 *   - active-row state on the selected entry
 *   - git vs local source-type badge differentiation (FR-004)
 *   - long-version truncation: ellipsis class + `title` exposes the
 *     full string (EC: long version labels)
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { VersionList } from "@/pages/drivers/driver-detail/VersionList";
import type { DriverVersionDetail } from "@/pages/drivers/driver-detail/types";

function makeVersion(
  overrides: Partial<DriverVersionDetail> & {
    id: string;
    version: string;
    createdOn: string;
  },
): DriverVersionDetail {
  const base = {
    supportedVersions: "*",
    sourceType: "git",
    sourceRepository: "https://github.com/example/repo.git",
    sourceBranch: "main" as string | null,
    sourcePath: null as string | null,
    components: null,
    parameters: [],
    componentConfigs: [],
    helmChart: {
      id: `chart-${overrides.id}`,
      name: "chart",
      version: "0.1.0",
      repository: "https://charts.example.com",
      valueTemplate: "{}",
    },
    actions: [],
  };
  return { ...base, ...overrides } as DriverVersionDetail;
}

describe("VersionList (T020)", () => {
  it("renders rows newest-first by createdOn regardless of array order", async () => {
    const versions: DriverVersionDetail[] = [
      makeVersion({
        id: "oldest",
        version: "1.0.0",
        createdOn: "2026-01-01T00:00:00Z",
      }),
      makeVersion({
        id: "newest",
        version: "1.2.0",
        createdOn: "2026-03-01T00:00:00Z",
      }),
      makeVersion({
        id: "middle",
        version: "1.1.0",
        createdOn: "2026-02-01T00:00:00Z",
      }),
    ];

    await render(
      <VersionList
        versions={versions}
        selectedVersionId={null}
        onSelect={vi.fn()}
      />,
    );

    const rows = screen.getAllByTestId("driver-version-row");
    expect(rows.map((r) => r.getAttribute("data-version-id"))).toEqual([
      "newest",
      "middle",
      "oldest",
    ]);
  });

  it("marks the selected row as active via aria-pressed + data-selected", async () => {
    const versions = [
      makeVersion({
        id: "v1",
        version: "1.0.0",
        createdOn: "2026-01-01T00:00:00Z",
      }),
      makeVersion({
        id: "v2",
        version: "2.0.0",
        createdOn: "2026-02-01T00:00:00Z",
      }),
    ];

    await render(
      <VersionList
        versions={versions}
        selectedVersionId="v1"
        onSelect={vi.fn()}
      />,
    );

    const rows = screen.getAllByTestId("driver-version-row");
    const v1 = rows.find((r) => r.getAttribute("data-version-id") === "v1")!;
    const v2 = rows.find((r) => r.getAttribute("data-version-id") === "v2")!;

    expect(v1).toHaveAttribute("aria-pressed", "true");
    expect(v1).toHaveAttribute("data-selected", "true");
    expect(v2).toHaveAttribute("aria-pressed", "false");
    expect(v2).toHaveAttribute("data-selected", "false");
  });

  it("differentiates the source-type badge between git and local versions", async () => {
    const versions: DriverVersionDetail[] = [
      makeVersion({
        id: "git-v",
        version: "1.0.0",
        createdOn: "2026-02-01T00:00:00Z",
        sourceType: "git",
      }),
      makeVersion({
        id: "local-v",
        version: "1.0.1",
        createdOn: "2026-01-01T00:00:00Z",
        sourceType: "local",
        sourceRepository: "",
        sourceBranch: null,
        sourcePath: "/tmp/local-driver",
      }),
    ];

    await render(
      <VersionList
        versions={versions}
        selectedVersionId={null}
        onSelect={vi.fn()}
      />,
    );

    const rows = screen.getAllByTestId("driver-version-row");
    const gitRow = rows.find(
      (r) => r.getAttribute("data-version-id") === "git-v",
    )!;
    const localRow = rows.find(
      (r) => r.getAttribute("data-version-id") === "local-v",
    )!;

    expect(gitRow).toHaveAttribute("data-source-type", "git");
    expect(gitRow.textContent).toContain("git");
    expect(localRow).toHaveAttribute("data-source-type", "local");
    expect(localRow.textContent).toContain("local");
  });

  it("truncates long version strings and exposes the full value via title", async () => {
    const longLabel =
      "1.2.3-very-long-prerelease-identifier.with.many.dotted.segments+build.42";
    const versions = [
      makeVersion({
        id: "long",
        version: longLabel,
        createdOn: "2026-01-01T00:00:00Z",
      }),
    ];

    await render(
      <VersionList
        versions={versions}
        selectedVersionId={null}
        onSelect={vi.fn()}
      />,
    );

    const row = screen.getByTestId("driver-version-row");
    const labelSpan = row.querySelector("span[title]")!;
    expect(labelSpan.getAttribute("title")).toBe(longLabel);
    expect(labelSpan.className).toContain("truncate");
  });
});
