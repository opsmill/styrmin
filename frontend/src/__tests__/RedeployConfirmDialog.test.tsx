import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils";

import { RedeployConfirmDialog } from "@/components/environment/RedeployConfirmDialog";

describe("RedeployConfirmDialog", () => {
  it("states 'No deployments will be redeployed' when count is 0 and keeps Redeploy enabled", async () => {
    await render(
      <RedeployConfirmDialog
        open
        deploymentCount={0}
        deploymentNames={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("redeploy-confirm-dialog-body"),
    ).toHaveTextContent("No deployments will be redeployed.");
    expect(screen.getByTestId("redeploy-confirm-redeploy")).toBeEnabled();
  });

  it("displays a single deployment name verbatim", async () => {
    await render(
      <RedeployConfirmDialog
        open
        deploymentCount={1}
        deploymentNames={["solo"]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("redeploy-confirm-dialog-body"),
    ).toHaveTextContent("1 deployment will be redeployed: solo.");
  });

  it("comma-separates 2-5 deployments", async () => {
    await render(
      <RedeployConfirmDialog
        open
        deploymentCount={3}
        deploymentNames={["a", "b", "c"]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("redeploy-confirm-dialog-body"),
    ).toHaveTextContent("3 deployments will be redeployed: a, b, c.");
  });

  it("truncates past 5 deployment names with 'and N more'", async () => {
    await render(
      <RedeployConfirmDialog
        open
        deploymentCount={8}
        deploymentNames={["a", "b", "c", "d", "e", "f", "g", "h"]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("redeploy-confirm-dialog-body"),
    ).toHaveTextContent(
      "8 deployments will be redeployed: a, b, c, d, e, and 3 more.",
    );
  });
});
