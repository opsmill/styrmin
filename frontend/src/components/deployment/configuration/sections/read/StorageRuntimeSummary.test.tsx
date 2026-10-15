/**
 * Read-only Storage & Runtime summary — backup retention tile
 * (016-backup-retention-ttl, FR-003 deepest-wins resolution).
 *
 * The tile answers "how long are this deployment's backups kept, and who
 * decided that?" from the Configuration tab, without cluster access.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { UpdateDeploymentInput } from "@/generated/graphql";
import { DEFAULT_BACKUP_TTL } from "@/lib/backup-ttl";

import { StorageRuntimeSummary } from "./StorageRuntimeSummary";

function renderSummary(
  scopes: {
    current?: UpdateDeploymentInput;
    environment?: UpdateDeploymentInput;
    cluster?: UpdateDeploymentInput;
  } = {},
) {
  return render(
    <StorageRuntimeSummary
      current={scopes.current ?? {}}
      environment={scopes.environment ?? {}}
      cluster={scopes.cluster ?? {}}
    />,
  );
}

/** The backup-retention tile's value element. */
function ttlTile(): HTMLElement {
  return screen.getByTestId("storage-backup-ttl");
}

describe("StorageRuntimeSummary: backup retention tile", () => {
  it("renders a BACKUP TTL tile alongside the pre-existing two", () => {
    renderSummary();

    expect(screen.getByText("DB SIZE")).toBeInTheDocument();
    expect(screen.getByText("STORAGE CLASS")).toBeInTheDocument();
    expect(screen.getByText("BACKUP TTL")).toBeInTheDocument();
  });

  it("shows the deployment's own value as a deployment-level override", () => {
    renderSummary({
      current: { backupTtl: "168h" },
      environment: { backupTtl: "2160h" },
      cluster: { backupTtl: "8760h" },
    });

    const tile = ttlTile();
    expect(tile.textContent).toContain("168h");
    // Deepest scope wins, so the shallower values must not leak through.
    expect(tile.textContent).not.toContain("2160h");
    expect(tile.textContent).not.toContain("8760h");
    // Not inherited: no parenthetical, no italic treatment.
    expect(tile.getAttribute("data-inherited")).toBe("false");
    expect(tile.textContent).not.toContain("(");
  });

  it("inherits the environment's value when the deployment sets none", () => {
    renderSummary({
      current: {},
      environment: { backupTtl: "2160h" },
      cluster: { backupTtl: "8760h" },
    });

    const tile = ttlTile();
    expect(tile.textContent).toContain("2160h");
    expect(tile.getAttribute("data-inherited")).toBe("true");
    expect(tile.getAttribute("data-origin")).toBe("env");
    // The operator is told which scope to go and edit.
    expect(tile.textContent).toContain("(env)");
  });

  it("inherits the cluster's value when neither deployment nor environment sets one", () => {
    // Without this layer the tile would claim the built-in default applies
    // while a cluster-wide policy was actually in force — a false statement
    // about what Velero will stamp on the next backup.
    renderSummary({
      current: {},
      environment: {},
      cluster: { backupTtl: "8760h" },
    });

    const tile = ttlTile();
    expect(tile.textContent).toContain("8760h");
    expect(tile.getAttribute("data-inherited")).toBe("true");
    expect(tile.getAttribute("data-origin")).toBe("cluster");
    expect(tile.textContent).toContain("(cluster)");
  });

  it("names the built-in default when no scope sets a policy", () => {
    // Never blank and never "not set": every backup gets a spec.ttl, so an
    // empty tile would imply backups are kept forever.
    renderSummary({ current: {}, environment: {}, cluster: {} });

    const tile = ttlTile();
    expect(tile.textContent).toContain(DEFAULT_BACKUP_TTL);
    expect(tile.textContent).toContain("720h");
    expect(tile.textContent).not.toContain("not set");
    expect(tile.textContent?.trim()).not.toBe("");
    expect(tile.getAttribute("data-inherited")).toBe("true");
    expect(tile.getAttribute("data-origin")).toBe("default");
    expect(tile.textContent).toContain("(default)");
  });

  it("treats an explicit null at a scope as 'sets no policy'", () => {
    // The projection yields null/undefined interchangeably for an absent key;
    // both must fall through to the next scope rather than render "null".
    renderSummary({
      current: { backupTtl: null },
      environment: { backupTtl: null },
      cluster: { backupTtl: "336h" },
    });

    const tile = ttlTile();
    expect(tile.textContent).toContain("336h");
    expect(tile.textContent).not.toContain("null");
    expect(tile.getAttribute("data-origin")).toBe("cluster");
  });

  it("leaves the pre-existing tiles' env-inheritance labelling untouched", () => {
    // The `origin` prop defaults to "env", so adding it must not change how
    // the two-scope tiles read.
    renderSummary({
      current: {},
      environment: { dbSize: "small" },
      cluster: {},
    });

    const dbSize = screen.getByText("small", { selector: "[data-inherited]" });
    expect(dbSize.getAttribute("data-inherited")).toBe("true");
    expect(dbSize.getAttribute("data-origin")).toBe("env");
    expect(dbSize.textContent).toBe("small(env)");
  });
});
