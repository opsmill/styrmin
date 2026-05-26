/**
 * Component test for the deployment configuration IdentitySection
 * (feature 013, T048).
 *
 * Coverage:
 *   - The `driverLabel` prop -- which ConfigEditDrawer composes as
 *     `${driverName}@${formatDriverVersionLabel(...)}` -- is rendered
 *     verbatim, containing the fingerprint short suffix.
 *
 * The drawer's composition logic itself is exercised at the helper level
 * (driverVersion.test.ts + driverVersion-applied-to-deployment below) so
 * this test only asserts the section faithfully surfaces the
 * already-formatted label.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { useForm } from "@tanstack/react-form";

import { IdentitySection } from "@/components/deployment/configuration/sections/edit/IdentitySection";
import { DrawerDiffProvider } from "@/components/deployment/configuration/DrawerDiffContext";
import { formatDriverVersionLabel } from "@/lib/driverVersion";
import type { UpdateDeploymentInput } from "@/generated/graphql";

function Harness({ driverLabel }: { driverLabel: string }) {
  const initialValues: UpdateDeploymentInput = {
    name: "my-deployment",
  } as UpdateDeploymentInput;
  const form = useForm({
    defaultValues: initialValues,
    onSubmit: () => undefined,
  });
  return (
    <DrawerDiffProvider
      form={form}
      initialValues={initialValues}
      driverSchema={[]}
    >
      <IdentitySection
        form={form}
        initial={initialValues}
        environment={initialValues}
        anchorId="identity"
        driverLabel={driverLabel}
        appVersion="1.2.3"
      />
    </DrawerDiffProvider>
  );
}

describe("IdentitySection driver label (feature 013, T048)", () => {
  it("renders the formatted <version>@<short> suffix in the driver label", () => {
    const label = formatDriverVersionLabel({
      version: "1.2.3",
      contentHash:
        "deadbeefcafefacefeedbabec0ffee1234567890abcdef0123456789abcdef01",
      sourceCommitSha: null,
    });
    expect(label).toBe("1.2.3@deadbee");

    render(<Harness driverLabel={`nginx@${label}`} />);

    const labelEl = screen.getByTestId("identity-driver-label");
    expect(labelEl).toHaveTextContent("nginx@1.2.3@deadbee");
  });

  it("renders the git short SHA in the driver label", () => {
    const label = formatDriverVersionLabel({
      version: "2.0.0",
      contentHash: null,
      sourceCommitSha: "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    });
    expect(label).toBe("2.0.0@a1b2c3d");

    render(<Harness driverLabel={`acme@${label}`} />);
    expect(screen.getByTestId("identity-driver-label")).toHaveTextContent(
      "acme@2.0.0@a1b2c3d",
    );
  });
});
