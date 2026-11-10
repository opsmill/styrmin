import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import { UpgradeErrorAlert } from "./UpgradeErrorAlert";

const GUIDE = "https://docs.styrmin.app/docs/drivers/changing-driver-versions";
const REPLICA_GUIDE =
  "https://docs.styrmin.app/docs/drivers/migrating-replica-parameters";

function retiredParameterError(): GraphQLOperationError {
  return new GraphQLOperationError(
    "RETIRED_PARAMETER_VALUE",
    `Parameter 'replicas_task_worker' is not declared by driver infrahub version 5 ` +
      `(application version 1.7.3), and this deployment sets it to 4 (default 2). ` +
      `Remove the parameter or reset it to its default, then change the driver version ` +
      `again. See ${GUIDE}. If it set a replica count, carry the value over as a ` +
      `replica override on the component first: ${REPLICA_GUIDE}`,
    {
      code: "RETIRED_PARAMETER_VALUE",
      parameter_name: "replicas_task_worker",
      value: 4,
      default: 2,
    },
  );
}

describe("UpgradeErrorAlert", () => {
  it("makes every link in the message clickable", () => {
    render(
      <UpgradeErrorAlert
        error={new Error(`Version 9 is not supported. See ${GUIDE}.`)}
        componentNames={[]}
        onOpenSettings={() => {}}
      />,
    );

    const link = screen.getByRole("link", { name: GUIDE });
    expect(link).toHaveAttribute("href", GUIDE);
    expect(link).toHaveAttribute("target", "_blank");
    // The full stop after the URL stays text.
    expect(screen.getByTestId("upgrade-error")).toHaveTextContent(
      `See ${GUIDE}.`,
    );
  });

  // A version change that would drop a service ingress override is refused with a
  // typed error (#598, FR-010). The message says "clear the override in the same
  // request", which the Upgrade dialog cannot do: it sends the version only. The
  // alert gives the steps on the Settings tab instead.
  describe("a dropped service ingress override", () => {
    const MESSAGES = {
      internal:
        "Service 'task-manager' has an ingress override, and driver version 1.8.0 declares that service with scope 'internal', and Styrmin does not build an Ingress for an internal service. Changing the driver version from 1.7.3 to 1.8.0 would drop the override. Clear the override of 'task-manager' in the same request, or keep a driver version that declares it external with kind 'http' or 'https'.",
      removed:
        "Service 'task-manager' has an ingress override, and driver version 1.8.0 does not declare that service. Changing the driver version from 1.7.3 to 1.8.0 would drop the override. Clear the override of 'task-manager' in the same request, or keep a driver version that declares it external with kind 'http' or 'https'.",
      not_http_or_https:
        "Service 'task-manager' has an ingress override, and driver version 1.8.0 declares that service with kind 'tcp', and Styrmin builds an Ingress only for kind 'http' or 'https'. Changing the driver version from 1.7.3 to 1.8.0 would drop the override. Clear the override of 'task-manager' in the same request, or keep a driver version that declares it external with kind 'http' or 'https'.",
    } as const;

    function renderDropped(
      reason: keyof typeof MESSAGES,
      onOpenSettings: () => void = () => {},
    ) {
      render(
        <UpgradeErrorAlert
          error={
            new GraphQLOperationError(
              "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED",
              MESSAGES[reason],
              {
                code: "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED",
                service_name: "task-manager",
                current_version: "1.7.3",
                target_version: "1.8.0",
                reason,
              },
            )
          }
          componentNames={["server"]}
          onOpenSettings={onOpenSettings}
        />,
      );
    }

    it.each(["internal", "removed", "not_http_or_https"] as const)(
      "names the service and the steps on the Settings tab (reason %s)",
      (reason) => {
        renderDropped(reason);

        const alert = screen.getByTestId("upgrade-dropped-ingress-override");
        expect(alert).toHaveTextContent(
          "Clear the ingress override of task-manager before you upgrade",
        );
        expect(alert).toHaveTextContent("Nothing changed.");
        const steps = screen
          .getAllByRole("listitem")
          .map((li) => li.textContent);
        expect(steps).toEqual([
          "On the Settings tab, click Update Settings.",
          "In the Edit configuration drawer, open the Services section.",
          "Under Service ingress overrides, click Clear for task-manager.",
          "Click Review & apply, then upgrade again.",
        ]);
        // The server message stays visible, with the versions and the reason.
        expect(alert).toHaveTextContent(MESSAGES[reason]);
        expect(screen.queryByTestId("upgrade-retired-parameter")).toBeNull();
      },
    );

    it("opens the Settings tab from the alert", async () => {
      const onOpenSettings = vi.fn();
      renderDropped("removed", onOpenSettings);

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Open the Settings tab" }));

      expect(onOpenSettings).toHaveBeenCalledTimes(1);
    });
  });

  it("gives the steps for a retired parameter and names its component", () => {
    render(
      <UpgradeErrorAlert
        error={retiredParameterError()}
        componentNames={["server", "task-worker"]}
        onOpenSettings={() => {}}
      />,
    );

    const alert = screen.getByTestId("upgrade-retired-parameter");
    expect(alert).toHaveTextContent(
      "Change replicas_task_worker before you upgrade",
    );
    expect(alert).toHaveTextContent(
      "This deployment sets it to 4, and its default is 2. Nothing changed.",
    );
    const steps = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(steps).toEqual([
      "Under Components, set Replicas of task-worker to 4, so it keeps its pod count.",
      "Under Driver Parameters, set replicas_task_worker back to 2.",
      "Click Review & apply, then upgrade again.",
    ]);
    expect(screen.getByRole("link", { name: GUIDE })).toHaveAttribute(
      "href",
      GUIDE,
    );
    expect(screen.getByRole("link", { name: REPLICA_GUIDE })).toBeVisible();
  });

  it("leaves out the replica step for a parameter that names no component", () => {
    const error = retiredParameterError();
    error.extensions.parameter_name = "enable_analytics";
    render(
      <UpgradeErrorAlert
        error={error}
        componentNames={["server", "task-worker"]}
        onOpenSettings={() => {}}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("opens the Settings tab from the alert", async () => {
    const onOpenSettings = vi.fn();
    render(
      <UpgradeErrorAlert
        error={retiredParameterError()}
        componentNames={["task-worker"]}
        onOpenSettings={onOpenSettings}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Open the Settings tab" }));

    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });
});
