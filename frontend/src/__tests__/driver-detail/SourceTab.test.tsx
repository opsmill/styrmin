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
    sourceCommitSha: null as string | null,
    contentHash: null as string | null,
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
    // local renderer does NOT leak branch information (FR-013 — branch
    // is intentionally omitted for local sources).
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

  it("renders the full commit SHA with a copyable Copy button on a git source (feature 013, T045)", () => {
    const commitSha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
    const version = makeVersion({
      id: "v-git-fp",
      version: "1.2.3",
      sourceType: "git",
      sourceRepository: "github.com/acme/driver",
      sourceBranch: "main",
      sourceCommitSha: commitSha,
    });

    render(<SourceTab version={version} />);

    const valueEl = screen.getByTestId("driver-source-commit-sha");
    expect(valueEl).toHaveTextContent(commitSha);
    expect(valueEl.textContent).toHaveLength(40);
    const copyBtn = screen.getByRole("button", { name: /copy commit sha/i });
    expect(copyBtn).toBeInTheDocument();
  });

  it("renders the full content hash with a copyable Copy button on a local source (feature 013, T045)", () => {
    const contentHash =
      "deadbeefcafefacefeedbabec0ffee1234567890abcdef0123456789abcdef01";
    const version = makeVersion({
      id: "v-local-fp",
      version: "0.1.0",
      sourceType: "local",
      sourcePath: "/tmp/local-driver",
      sourceRepository: "",
      sourceBranch: null,
      contentHash,
    });

    render(<SourceTab version={version} />);

    const valueEl = screen.getByTestId("driver-source-content-hash");
    expect(valueEl).toHaveTextContent(contentHash);
    expect(valueEl.textContent).toHaveLength(64);
    const copyBtn = screen.getByRole("button", { name: /copy content hash/i });
    expect(copyBtn).toBeInTheDocument();
  });
});
