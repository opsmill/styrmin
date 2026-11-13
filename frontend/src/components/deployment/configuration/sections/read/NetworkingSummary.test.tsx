import { describe, it, expect } from "vitest";
import { render, screen, within } from "@/test/utils";

import { NetworkingSummary } from "./NetworkingSummary";

/**
 * Tests for the per-service part of the Networking summary (#598, US3,
 * FR-016): the effective ingress class and host of each service, each marked
 * as overridden or inherited. Written before the component (T045): the
 * component does not yet take the `services` prop, so the tests on the
 * per-service rows fail until then.
 *
 * Contract the tests assume (T045 implements it):
 * - Each service is a `role="group"` named by its driver service name.
 * - Inside it, two rows `data-testid="summary-row"` (the existing
 *   `SummaryRow`): label `Ingress class` and label `Host`, each with the value
 *   in the row's `<dd>`, and the text `Overridden` or `Inherited` in the row
 *   but outside the `<dd>`.
 * - The class is `ingressClass` and its mark is `ingressClassOverridden`; the
 *   host is `humanReadableFqdn` and its mark is `fqdnSuffixOverridden`.
 */

interface ServiceRow {
  driverServiceName: string;
  resolvedName: string;
  scope: string;
  kind: string;
  ingressClass: string | null;
  ingressClassOverridden: boolean;
  humanReadableFqdn: string | null;
  fqdnSuffixOverridden: boolean;
}

const CLUSTER_CONFIG = { fqdn_suffix: "styrmin.com", ingress_class: "traefik" };

const TASK_MANAGER_OVERRIDDEN: ServiceRow = {
  driverServiceName: "task-manager",
  resolvedName: "task-manager",
  scope: "external",
  kind: "http",
  ingressClass: "tailscale",
  ingressClassOverridden: true,
  humanReadableFqdn: "task-manager-prod.tailnet.example.ts.net",
  fqdnSuffixOverridden: true,
};

const WEB_INHERITED: ServiceRow = {
  driverServiceName: "web",
  resolvedName: "web",
  scope: "external",
  kind: "https",
  ingressClass: "traefik",
  ingressClassOverridden: false,
  humanReadableFqdn: "web-prod.styrmin.com",
  fqdnSuffixOverridden: false,
};

/**
 * The `services` prop is passed through a spread so that this file type-checks
 * before T045 declares it in the component's `Props`. TypeScript does not check
 * the excess properties of a JSX spread, and the runtime behaviour is the same
 * as a named prop. T045 may pass it as a named attribute, typed from the
 * `deployedServices` of `GetDeploymentQuery` once the query selects the new
 * fields.
 */
async function renderSummary(services?: readonly ServiceRow[]) {
  const plannedProps = services === undefined ? {} : { services };
  await render(
    <NetworkingSummary
      deploymentConfig={{}}
      environmentConfig={{}}
      clusterConfig={CLUSTER_CONFIG}
      {...plannedProps}
    />,
  );
}

function serviceGroup(name: string): HTMLElement {
  return screen.getByRole("group", { name });
}

function valueRow(group: HTMLElement, label: string): HTMLElement {
  const row = within(group)
    .getAllByTestId("summary-row")
    .find(
      (candidate) =>
        within(candidate).queryByRole("term")?.textContent === label,
    );
  if (!row) throw new Error(`No "${label}" row in the group`);
  return row;
}

function expectRow(
  group: HTMLElement,
  label: string,
  value: string,
  mark: "Overridden" | "Inherited",
): void {
  const row = valueRow(group, label);
  expect(within(row).getByRole("definition")).toHaveTextContent(
    new RegExp(`^${value.replaceAll(".", "\\.")}$`),
  );
  const other = mark === "Overridden" ? "Inherited" : "Overridden";
  expect(within(row).getByText(mark)).toBeInTheDocument();
  expect(within(row).queryByText(other)).toBeNull();
}

describe("NetworkingSummary: deployment-wide rows (unchanged)", () => {
  it("shows the resolved FQDN suffix and ingress class, with or without services", async () => {
    await renderSummary();

    expect(
      screen.getByRole("heading", { name: "Networking" }),
    ).toBeInTheDocument();
    const suffix = screen
      .getAllByTestId("summary-row")
      .find(
        (row) => within(row).queryByRole("term")?.textContent === "FQDN suffix",
      );
    expect(within(suffix!).getByRole("definition")).toHaveTextContent(
      "styrmin.com",
    );
    const ingressClass = screen
      .getAllByTestId("summary-row")
      .find(
        (row) =>
          within(row).queryByRole("term")?.textContent === "Ingress class",
      );
    expect(within(ingressClass!).getByRole("definition")).toHaveTextContent(
      "traefik",
    );
  });
});

describe("NetworkingSummary: per-service class and host (FR-016)", () => {
  it.each([
    [true, "Enabled"],
    [false, "Disabled"],
  ])("shows explicit TLS %s in the service summary", async (tls, label) => {
    await render(
      <NetworkingSummary
        deploymentConfig={{ services: { "task-manager": { tls } } }}
        environmentConfig={{}}
        clusterConfig={CLUSTER_CONFIG}
        services={[TASK_MANAGER_OVERRIDDEN, WEB_INHERITED]}
      />,
    );

    expect(
      within(valueRow(serviceGroup("task-manager"), "TLS hosts")).getByRole(
        "definition",
      ),
    ).toHaveTextContent(label);
    expect(within(serviceGroup("web")).queryByText("TLS hosts")).toBeNull();
  });

  it("shows an overridden service with its override class and host, both marked overridden", async () => {
    await renderSummary([TASK_MANAGER_OVERRIDDEN, WEB_INHERITED]);

    const group = serviceGroup("task-manager");
    expectRow(group, "Ingress class", "tailscale", "Overridden");
    expectRow(
      group,
      "Host",
      "task-manager-prod.tailnet.example.ts.net",
      "Overridden",
    );
  });

  it("shows a service without an override with the resolved class and host, both marked inherited", async () => {
    await renderSummary([TASK_MANAGER_OVERRIDDEN, WEB_INHERITED]);

    const group = serviceGroup("web");
    expectRow(group, "Ingress class", "traefik", "Inherited");
    expectRow(group, "Host", "web-prod.styrmin.com", "Inherited");
  });

  it("marks the class and the host separately when only one of them is overridden", async () => {
    await renderSummary([
      {
        ...TASK_MANAGER_OVERRIDDEN,
        fqdnSuffixOverridden: false,
        humanReadableFqdn: "task-manager-prod.styrmin.com",
      },
    ]);

    const group = serviceGroup("task-manager");
    expectRow(group, "Ingress class", "tailscale", "Overridden");
    expectRow(group, "Host", "task-manager-prod.styrmin.com", "Inherited");
  });

  it("lists no group for an external service of kind tcp or udp, and none for an internal one", async () => {
    await renderSummary([
      WEB_INHERITED,
      { ...WEB_INHERITED, driverServiceName: "queue", kind: "tcp" },
      { ...WEB_INHERITED, driverServiceName: "metrics", kind: "udp" },
      { ...WEB_INHERITED, driverServiceName: "database", scope: "internal" },
    ]);

    expect(serviceGroup("web")).toBeInTheDocument();
    for (const name of ["queue", "metrics", "database"]) {
      expect(screen.queryByRole("group", { name })).toBeNull();
    }
  });

  it("marks a service with no override at all as inherited, as the spec scenario 3 requires", async () => {
    await renderSummary([WEB_INHERITED]);

    const group = serviceGroup("web");
    expect(within(group).queryByText("Overridden")).toBeNull();
    expect(within(group).getAllByText("Inherited")).toHaveLength(2);
  });
});
