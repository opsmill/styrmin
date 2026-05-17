import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils";
import type { UpdateDeploymentInput } from "@/generated/graphql";
import type {
  DriverParameterSchema,
  InheritanceState,
  SectionId,
} from "@/lib/configuration-types";
import { HeroSummaryBar } from "./HeroSummaryBar";

/**
 * Minimal fixtures — the hero bar's permission gate (FR-030) is the only
 * behaviour under test here. Field-count math is covered indirectly by
 * the read-tab E2E test.
 */
function makeProps(canEdit: boolean) {
  const driverSchema: DriverParameterSchema = [];
  const inheritance = new Map<SectionId, InheritanceState>();
  const current: UpdateDeploymentInput = {};
  return {
    deployment: { id: "dep-1", name: "demo" },
    environment: { id: "env-1", name: "prod" },
    driverSchema,
    inheritance,
    current,
    canEdit,
    onEditClick: vi.fn(),
    onViewJsonClick: vi.fn(),
  };
}

describe("HeroSummaryBar permission gating (FR-030)", () => {
  it("renders the Edit configuration button when canEdit=true", async () => {
    await render(<HeroSummaryBar {...makeProps(true)} />);

    expect(screen.getByTestId("hero-edit-config-button")).toBeInTheDocument();
    expect(screen.getByTestId("hero-view-json-button")).toBeInTheDocument();
  });

  it("omits the Edit configuration button when canEdit=false", async () => {
    await render(<HeroSummaryBar {...makeProps(false)} />);

    expect(
      screen.queryByTestId("hero-edit-config-button"),
    ).not.toBeInTheDocument();
    // The View JSON action is always available; it is not gated by canEdit.
    expect(screen.getByTestId("hero-view-json-button")).toBeInTheDocument();
  });
});
