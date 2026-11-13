import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import type { ServiceConfigInput } from "@/generated/graphql";
import { ServiceIngressFields } from "./ServiceIngressFields";

function Harness({ initial = [] }: { initial?: ServiceConfigInput[] }) {
  const [rows, setRows] = useState(initial);
  return (
    <>
      <ServiceIngressFields
        services={[
          {
            driverServiceName: "task-manager",
            scope: "external",
            kind: "http",
          },
        ]}
        value={rows}
        onChange={setRows}
      />
      <output data-testid="stored-rows">{JSON.stringify(rows)}</output>
    </>
  );
}

describe("service ingress TLS", () => {
  it("enables TLS without dropping the address override, and clears it with the row", async () => {
    const user = userEvent.setup();
    await render(
      <Harness
        initial={[{ name: "task-manager", ingressClass: "tailscale" }]}
      />,
    );
    const checkbox = screen.getByRole("checkbox", {
      name: "TLS hosts for task-manager",
    });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(JSON.parse(screen.getByTestId("stored-rows").textContent!)).toEqual([
      { name: "task-manager", ingressClass: "tailscale", tls: true },
    ]);
    await user.click(
      screen.getByRole("button", {
        name: "Clear ingress override for task-manager",
      }),
    );
    expect(checkbox).not.toBeChecked();
    expect(screen.getByTestId("stored-rows")).toHaveTextContent("[]");
  });

  it("reads stored TLS and lets the operator disable it", async () => {
    const user = userEvent.setup();
    await render(<Harness initial={[{ name: "task-manager", tls: true }]} />);
    const checkbox = screen.getByRole("checkbox", {
      name: "TLS hosts for task-manager",
    });
    expect(checkbox).toBeChecked();
    await user.click(checkbox);
    expect(checkbox).not.toBeChecked();
    expect(
      JSON.parse(screen.getByTestId("stored-rows").textContent!)[0].tls,
    ).toBeNull();
  });
});
