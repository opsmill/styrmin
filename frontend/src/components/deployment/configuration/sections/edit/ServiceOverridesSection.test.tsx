import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { useForm, type AnyFormApi } from "@tanstack/react-form";

import type {
  ServiceConfigInput,
  UpdateDeploymentInput,
} from "@/generated/graphql";

import { DrawerDiffProvider } from "../../DrawerDiffContext";
import { DrawerFooter } from "../../DrawerFooter";
import {
  ServiceOverridesSection,
  serviceOverridesSchema,
} from "./ServiceOverridesSection";

describe("serviceOverridesSchema", () => {
  it("accepts a valid override list", () => {
    const result = serviceOverridesSchema.safeParse([
      { driverServiceName: "api", overrideName: "my-api" },
      { driverServiceName: "worker", overrideName: "my-worker" },
    ]);
    expect(result.success).toBe(true);
  });

  it("rejects an override name with uppercase letters", () => {
    const result = serviceOverridesSchema.safeParse([
      { driverServiceName: "api", overrideName: "BadName" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate driver service names", () => {
    const result = serviceOverridesSchema.safeParse([
      { driverServiceName: "api", overrideName: "a" },
      { driverServiceName: "api", overrideName: "b" },
    ]);
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Service ingress override fields (#598, US3, FR-015). Written before the
// component (T043, T044): the section does not yet take the `services` prop or
// render the fields below, so these tests fail until then.
// ---------------------------------------------------------------------------

/**
 * The services of the deployment with their scope, as the drawer passes them
 * from `deployment.deployedServices` (T044). `infrahub` is internal, so
 * Styrmin builds no Ingress for it and it must not get override fields.
 */
const SERVICES = [
  { driverServiceName: "infrahub", scope: "internal", kind: "http" },
  { driverServiceName: "task-manager", scope: "external", kind: "http" },
  { driverServiceName: "web", scope: "external", kind: "https" },
  // External, but Styrmin builds an Ingress only for http and https (review F4).
  { driverServiceName: "queue", scope: "external", kind: "tcp" },
  { driverServiceName: "metrics", scope: "external", kind: "udp" },
];

/**
 * The new prop is passed through a spread so that this file type-checks before
 * T043 declares it in the section's `Props`. TypeScript does not check the
 * excess properties of a JSX spread; the runtime behaviour is the same as a
 * named prop. T043 may pass it as a named attribute.
 */
const plannedProps = { services: SERVICES };

/** Mount the section against a real TanStack Form, as `ConfigEditDrawer` does. */
function Harness({
  initial,
  publish,
}: {
  initial: UpdateDeploymentInput;
  publish: (form: AnyFormApi) => void;
}) {
  const form = useForm({ defaultValues: initial });
  useEffect(() => {
    publish(form);
  }, [form, publish]);
  return (
    <DrawerDiffProvider form={form} initialValues={initial} driverSchema={[]}>
      <ServiceOverridesSection
        form={form}
        initial={initial}
        environment={{}}
        anchorId="serviceOverrides"
        driverServiceNames={SERVICES.map((s) => s.driverServiceName)}
        {...plannedProps}
      />
      <DrawerFooter onDiscard={() => {}} onReviewApply={() => {}} />
    </DrawerDiffProvider>
  );
}

function renderSection(initial: UpdateDeploymentInput = {}) {
  let formApi: AnyFormApi | undefined;
  render(
    <Harness
      initial={initial}
      publish={(form) => {
        formApi = form;
      }}
    />,
  );
  const values = () => formApi!.state.values as UpdateDeploymentInput;
  /**
   * The overrides that would take effect: rows with a class or a suffix. A row
   * with neither is no override (contract: "a row with both null is treated as
   * no override"), so the component may keep or drop such a row.
   */
  const overrides = (): ServiceConfigInput[] =>
    (values().services ?? []).filter(
      (row) => row.ingressClass || row.fqdnSuffix,
    );
  return { values, overrides };
}

const classField = (service: string) =>
  screen.getByLabelText(`Ingress class for ${service}`);
const suffixField = (service: string) =>
  screen.getByLabelText(`FQDN suffix for ${service}`);
const applyButton = () => screen.getByTestId("drawer-review-apply-button");
const pendingCount = () => screen.getByTestId("drawer-pending-count");

const TASK_MANAGER: ServiceConfigInput = {
  name: "task-manager",
  ingressClass: "tailscale",
  fqdnSuffix: "tailnet.example.ts.net",
};
const WEB: ServiceConfigInput = {
  name: "web",
  ingressClass: "traefik",
  fqdnSuffix: "web.example.com",
};

describe("ServiceOverridesSection: service name overrides stay", () => {
  it("still shows the stored service name overrides and the add control", () => {
    renderSection({
      serviceNameOverrides: [
        { driverServiceName: "infrahub", overrideName: "infrahub-enterprise" },
      ],
    });

    expect(screen.getByTestId("svc-override-0")).toHaveValue(
      "infrahub-enterprise",
    );
    expect(screen.getByTestId("add-service-override")).toBeInTheDocument();
  });
});

describe("ServiceOverridesSection: ingress override fields", () => {
  it("offers an ingress class and an FQDN suffix field for each external service", () => {
    renderSection();

    for (const service of ["task-manager", "web"]) {
      expect(classField(service)).toBeInTheDocument();
      expect(suffixField(service)).toBeInTheDocument();
    }
  });

  it("offers no ingress field for an internal service (FR-009 is prevented in the UI)", () => {
    renderSection();

    // The external service next to it has the fields, so an absent field here
    // is a decision of the component and not an empty render.
    expect(classField("task-manager")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ingress class for infrahub")).toBeNull();
    expect(screen.queryByLabelText("FQDN suffix for infrahub")).toBeNull();
  });

  it("offers no ingress field for an external tcp or udp service", () => {
    renderSection();

    expect(classField("task-manager")).toBeInTheDocument();
    for (const service of ["queue", "metrics"]) {
      expect(
        screen.queryByLabelText(`Ingress class for ${service}`),
      ).toBeNull();
      expect(screen.queryByLabelText(`FQDN suffix for ${service}`)).toBeNull();
    }
  });

  it("shows the stored override of each service in its own fields", () => {
    renderSection({ services: [TASK_MANAGER] });

    expect(classField("task-manager")).toHaveValue("tailscale");
    expect(suffixField("task-manager")).toHaveValue("tailnet.example.ts.net");
    expect(classField("web")).toHaveValue("");
    expect(suffixField("web")).toHaveValue("");
  });

  it("sets the class and the suffix of one service and leaves the others alone", async () => {
    const { overrides } = renderSection();
    expect(pendingCount()).toHaveTextContent("No pending changes");

    fireEvent.change(classField("task-manager"), {
      target: { value: "tailscale" },
    });
    fireEvent.change(suffixField("task-manager"), {
      target: { value: "tailnet.example.ts.net" },
    });

    await waitFor(() => expect(overrides()).toEqual([TASK_MANAGER]));
    expect(classField("web")).toHaveValue("");
    expect(suffixField("web")).toHaveValue("");
    await waitFor(() =>
      expect(pendingCount()).toHaveTextContent("2 pending changes"),
    );
    expect(applyButton()).toBeEnabled();
  });

  it("changes one field and keeps the other", async () => {
    const { overrides } = renderSection({ services: [TASK_MANAGER] });

    fireEvent.change(classField("task-manager"), {
      target: { value: "traefik" },
    });

    await waitFor(() =>
      expect(overrides()).toEqual([
        { ...TASK_MANAGER, ingressClass: "traefik" },
      ]),
    );
    expect(suffixField("task-manager")).toHaveValue("tailnet.example.ts.net");
    await waitFor(() =>
      expect(pendingCount()).toHaveTextContent("1 pending change"),
    );
  });

  it("clears one field by emptying it and keeps the other", async () => {
    const { overrides } = renderSection({ services: [TASK_MANAGER] });

    fireEvent.change(classField("task-manager"), { target: { value: "" } });

    await waitFor(() => expect(overrides()).toHaveLength(1));
    const [row] = overrides();
    expect(row.name).toBe("task-manager");
    expect(row.fqdnSuffix).toBe("tailnet.example.ts.net");
    expect(row.ingressClass || "").toBe("");
  });

  it("clears the whole override of one service with the clear action", async () => {
    const { overrides } = renderSection({ services: [TASK_MANAGER, WEB] });
    expect(pendingCount()).toHaveTextContent("No pending changes");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Clear ingress override for task-manager",
      }),
    );

    // Full replacement: the service that is not in the list has no override.
    await waitFor(() => expect(overrides()).toEqual([WEB]));
    expect(classField("task-manager")).toHaveValue("");
    expect(suffixField("task-manager")).toHaveValue("");
    expect(classField("web")).toHaveValue("traefik");
    expect(suffixField("web")).toHaveValue("web.example.com");
    await waitFor(() =>
      expect(pendingCount()).toHaveTextContent("2 pending changes"),
    );
    expect(applyButton()).toBeEnabled();
  });
});

describe("ServiceOverridesSection: FQDN suffix validation", () => {
  // The rule of the backend (`validate_service_fqdn_suffix`, data-model.md):
  // dot-separated labels of lowercase letters, digits and hyphens, each label
  // starting and ending with a letter or a digit and at most 63 characters, at
  // most 253 characters in total, no leading, trailing or doubled dot.
  const LABEL_63 = "a".repeat(63);
  const TOTAL_253 = `${LABEL_63}.${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(61)}`;
  const TOTAL_254 = `${LABEL_63}.${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(62)}`;

  it.each([
    ["a leading dot", ".example.com"],
    ["a trailing dot", "example.com."],
    ["a doubled dot", "example..com"],
    ["an uppercase letter", "Example.com"],
    ["an underscore", "exa_mple.com"],
    ["a space", "exa mple.com"],
    ["a label that starts with a hyphen", "-bad.example.com"],
    ["a label that ends with a hyphen", "bad-.example.com"],
    ["a label of 64 characters", `${"a".repeat(64)}.example.com`],
    ["254 characters in total", TOTAL_254],
  ])("rejects a suffix with %s", async (_why, value) => {
    renderSection();

    fireEvent.change(suffixField("task-manager"), { target: { value } });

    await waitFor(() =>
      expect(suffixField("task-manager")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    // The message names the rule, as the backend's does.
    expect(suffixField("task-manager")).toHaveAccessibleDescription(
      /DNS name/i,
    );
    // Only the suffix field is flagged, and Review & apply stays blocked.
    expect(classField("task-manager")).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(applyButton()).toBeDisabled();
  });

  it.each([
    ["a name with several labels", "tailnet.example.ts.net"],
    ["a single label", "internal"],
    ["a hyphen inside a label", "my-tailnet.ts.net"],
    ["a label that starts with a digit", "1.example.com"],
    ["a label of 63 characters", `${LABEL_63}.example.com`],
    ["253 characters in total", TOTAL_253],
  ])("accepts a suffix with %s", async (_why, value) => {
    renderSection();

    fireEvent.change(suffixField("task-manager"), { target: { value } });

    await waitFor(() => expect(applyButton()).toBeEnabled());
    expect(suffixField("task-manager")).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("unblocks Review & apply when the invalid suffix is fixed", async () => {
    renderSection();

    fireEvent.change(suffixField("task-manager"), {
      target: { value: "Example.com" },
    });
    await waitFor(() => expect(applyButton()).toBeDisabled());

    fireEvent.change(suffixField("task-manager"), {
      target: { value: "example.com" },
    });

    await waitFor(() => expect(applyButton()).toBeEnabled());
    expect(suffixField("task-manager")).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("does not flag an empty suffix: it means no suffix override", async () => {
    renderSection({ services: [TASK_MANAGER] });

    fireEvent.change(suffixField("task-manager"), { target: { value: "" } });

    await waitFor(() =>
      expect(pendingCount()).toHaveTextContent("1 pending change"),
    );
    expect(suffixField("task-manager")).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(applyButton()).toBeEnabled();
  });
});

// The ingress class is written to an Ingress (`ingressClassName` and an
// annotation), so the backend accepts only a Kubernetes object name (#598).
describe("ServiceOverridesSection: ingress class validation", () => {
  it.each([
    // A line break cannot reach a text input (the browser and jsdom strip it); the
    // rule that rejects one is covered in `lib/ingress-class.test.ts`.
    ["a space", "my class"],
    ["a tab", "tra\tefik"],
    ["an uppercase letter", "Traefik"],
    ["an underscore", "my_class"],
    ["a slash", "a/b"],
    ["a leading hyphen", "-traefik"],
    ["a trailing dot", "traefik."],
    [
      "254 characters in total",
      `${"a".repeat(63)}.${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(62)}`,
    ],
  ])("rejects a class with %s", async (_why, value) => {
    renderSection();

    fireEvent.change(classField("task-manager"), { target: { value } });

    await waitFor(() =>
      expect(classField("task-manager")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    expect(classField("task-manager")).toHaveAccessibleDescription(
      /Kubernetes object name/i,
    );
    // Only the class field is flagged, and Review & apply stays blocked with a hint that names the service.
    expect(suffixField("task-manager")).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(applyButton()).toBeDisabled();
    expect(screen.getByTestId("drawer-invalid-hint")).toHaveTextContent(
      "Fix the invalid ingress class on task-manager before applying.",
    );
  });

  it.each([["traefik"], ["prod-nginx"], ["k8s.io-ingress-nginx"], ["1class"]])(
    "accepts the class %s",
    async (value) => {
      renderSection();

      fireEvent.change(classField("task-manager"), { target: { value } });

      await waitFor(() => expect(applyButton()).toBeEnabled());
      expect(classField("task-manager")).not.toHaveAttribute(
        "aria-invalid",
        "true",
      );
    },
  );

  it("unblocks Review & apply when the invalid class is fixed", async () => {
    renderSection();

    fireEvent.change(classField("task-manager"), {
      target: { value: "Bad Class" },
    });
    await waitFor(() => expect(applyButton()).toBeDisabled());

    fireEvent.change(classField("task-manager"), {
      target: { value: "traefik" },
    });

    await waitFor(() => expect(applyButton()).toBeEnabled());
  });
});
