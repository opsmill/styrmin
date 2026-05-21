/**
 * Unit tests for the driver-detail Source tab (T026).
 *
 * Coverage:
 *   - "git" branch renders the repository URL, branch, and subpath
 *     (FR-012). The "Local path" label MUST NOT appear.
 *   - "local" branch renders the local source path (FR-013). The branch
 *     value MUST NOT leak into the rendered output — even when the mock
 *     version still carries a `sourceBranch` value.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { SourceTab } from "@/pages/drivers/driver-detail/tabs/SourceTab";
import type { DriverVersionDetail } from "@/pages/drivers/driver-detail/types";

function makeVersion(
  overrides: Partial<DriverVersionDetail> & {
    id: string;
    version: string;
    sourceType: string;
  },
): DriverVersionDetail {
  const base = {
    supportedVersions: "*",
    sourceRepository: "",
    sourceBranch: null as string | null,
    sourcePath: null as string | null,
    createdOn: "2026-01-01T00:00:00Z",
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

describe("SourceTab (T026)", () => {
  it("git branch renders repository URL, branch, and subpath", () => {
    const version = makeVersion({
      id: "v-git",
      version: "1.0.0",
      sourceType: "git",
      sourceRepository: "github.com/acme/nginx-driver",
      sourceBranch: "main",
      sourcePath: "/charts/web",
    });

    render(<SourceTab version={version} />);

    expect(screen.getByTestId("driver-source-git")).toBeInTheDocument();
    expect(screen.getByTestId("driver-source-repository")).toHaveTextContent(
      "github.com/acme/nginx-driver",
    );
    expect(screen.getByTestId("driver-source-branch")).toHaveTextContent(
      "main",
    );
    expect(screen.getByTestId("driver-source-path")).toHaveTextContent(
      "/charts/web",
    );

    // The "Local path" label belongs to the local branch and must not
    // appear in the git branch.
    expect(screen.queryByText("Local path")).not.toBeInTheDocument();
    expect(screen.queryByTestId("driver-source-local")).not.toBeInTheDocument();
  });

  it("git branch omits branch row when sourceBranch is null", () => {
    const version = makeVersion({
      id: "v-git-nobranch",
      version: "1.0.0",
      sourceType: "git",
      sourceRepository: "github.com/acme/nginx-driver",
      sourceBranch: null,
      sourcePath: null,
    });

    render(<SourceTab version={version} />);

    expect(screen.getByTestId("driver-source-repository")).toHaveTextContent(
      "github.com/acme/nginx-driver",
    );
    expect(
      screen.queryByTestId("driver-source-branch"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Branch")).not.toBeInTheDocument();
  });

  it("local branch renders the local path and never the branch value", () => {
    // The mock deliberately sets `sourceBranch` so the test proves the
    // local renderer does NOT leak branch information (FR-013 / EC-006).
    const version = makeVersion({
      id: "v-local",
      version: "0.2.0",
      sourceType: "local",
      sourcePath: "/Users/damien/drivers/nginx",
      sourceBranch: "main",
      sourceRepository: "",
    });

    render(<SourceTab version={version} />);

    expect(screen.getByTestId("driver-source-local")).toBeInTheDocument();
    expect(screen.getByText("Local path")).toBeInTheDocument();
    expect(screen.getByTestId("driver-source-path")).toHaveTextContent(
      "/Users/damien/drivers/nginx",
    );

    // Critical: the branch value must NOT appear anywhere in the local
    // source rendering.
    expect(screen.queryByText("main")).not.toBeInTheDocument();
    expect(screen.queryByText("Branch")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("driver-source-branch"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("driver-source-git")).not.toBeInTheDocument();
  });
});
