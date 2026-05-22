/**
 * Unit tests for the driver-detail Components and Actions tabs (T024).
 *
 * Coverage:
 *   - ComponentsTab MUST NOT render any `<pre>` element under any input
 *     branch (FR-009 / FR-018) — null, malformed (array), empty object,
 *     well-shaped object, well-shaped object with extra scalar fields, and
 *     a value-not-an-object entry that should silently fall through.
 *   - ActionsTab renders the empty state when the array is empty and one
 *     card per action otherwise, each surfacing name / description /
 *     location (FR-010 / FR-019).
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { ComponentsTab } from "@/pages/drivers/driver-detail/tabs/ComponentsTab";
import { ActionsTab } from "@/pages/drivers/driver-detail/tabs/ActionsTab";
import type { DriverAction } from "@/pages/drivers/driver-detail/types";

describe("ComponentsTab (T024)", () => {
  it("renders the empty state when components is null", () => {
    const { container } = render(<ComponentsTab components={null} />);
    expect(screen.getByTestId("driver-components-empty")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders the empty state when components is an array (malformed)", () => {
    const { container } = render(
      <ComponentsTab components={[] as unknown as Record<string, unknown>} />,
    );
    expect(screen.getByTestId("driver-components-empty")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders the empty state when components is an empty object", () => {
    const { container } = render(<ComponentsTab components={{}} />);
    expect(screen.getByTestId("driver-components-empty")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders a well-shaped component with only identifier.label", () => {
    const { container } = render(
      <ComponentsTab
        components={{
          server: {
            identifier: {
              label: {
                "app.kubernetes.io/name": "infrahub-server",
              },
            },
          },
        }}
      />,
    );
    expect(container.querySelector("pre")).toBeNull();
    const row = screen.getByTestId("driver-component-row");
    expect(row.getAttribute("data-component-name")).toBe("server");
    expect(within(row).getByText("server")).toBeInTheDocument();
    // The label key and value are both visible.
    expect(within(row).getByText("app.kubernetes.io/name")).toBeInTheDocument();
    expect(within(row).getByText("infrahub-server")).toBeInTheDocument();
  });

  it("renders identifier.label plus extra scalar fields as readable rows", () => {
    const { container } = render(
      <ComponentsTab
        components={{
          worker: {
            identifier: {
              label: { role: "primary" },
            },
            cpu: "500m",
            memory: "1Gi",
            enabled: true,
          },
        }}
      />,
    );
    expect(container.querySelector("pre")).toBeNull();
    const row = screen.getByTestId("driver-component-row");
    expect(row.getAttribute("data-component-name")).toBe("worker");
    // identifier.label is surfaced (key + value both visible).
    expect(within(row).getByText("role")).toBeInTheDocument();
    expect(within(row).getByText("primary")).toBeInTheDocument();
    // Extra scalar fields appear as key/value rows.
    expect(within(row).getByText("cpu")).toBeInTheDocument();
    expect(within(row).getByText("500m")).toBeInTheDocument();
    expect(within(row).getByText("memory")).toBeInTheDocument();
    expect(within(row).getByText("1Gi")).toBeInTheDocument();
    expect(within(row).getByText("enabled")).toBeInTheDocument();
    expect(within(row).getByText("true")).toBeInTheDocument();
  });

  it("silently skips a component whose value is not a plain object", () => {
    // Only `bad-entry` is invalid; nothing else is declared, so the
    // overall result should be the empty state — and importantly no
    // <pre> JSON fallback.
    const { container } = render(
      <ComponentsTab
        components={{
          "bad-entry": "i am not an object" as unknown as Record<
            string,
            unknown
          >,
        }}
      />,
    );
    expect(container.querySelector("pre")).toBeNull();
    expect(screen.getByTestId("driver-components-empty")).toBeInTheDocument();
    expect(
      screen.queryByTestId("driver-component-row"),
    ).not.toBeInTheDocument();
  });
});

describe("ActionsTab (T024)", () => {
  it("renders the empty state when no actions are declared", () => {
    render(<ActionsTab actions={[]} />);
    expect(screen.getByTestId("driver-actions-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("driver-action-card")).not.toBeInTheDocument();
  });

  it("renders one card per action with name, description, and location", () => {
    const actions: DriverAction[] = [
      {
        id: "act-1",
        name: "flush-cache",
        description: "Flush the in-process cache",
        location: "cache/flush",
      },
      {
        id: "act-2",
        name: "rotate-keys",
        description: "Rotate signing keys",
        location: "auth/rotate",
      },
    ];

    render(<ActionsTab actions={actions} />);

    const cards = screen.getAllByTestId("driver-action-card");
    expect(cards).toHaveLength(2);

    const first = cards[0]!;
    expect(first.getAttribute("data-action-id")).toBe("act-1");
    expect(within(first).getByText("flush-cache")).toBeInTheDocument();
    expect(
      within(first).getByText("Flush the in-process cache"),
    ).toBeInTheDocument();
    expect(within(first).getByText("cache/flush")).toBeInTheDocument();

    const second = cards[1]!;
    expect(second.getAttribute("data-action-id")).toBe("act-2");
    expect(within(second).getByText("rotate-keys")).toBeInTheDocument();
    expect(within(second).getByText("Rotate signing keys")).toBeInTheDocument();
    expect(within(second).getByText("auth/rotate")).toBeInTheDocument();
  });
});
