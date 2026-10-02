import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { useForm, type AnyFormApi } from "@tanstack/react-form";

import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";

import { DrawerDiffProvider } from "../../DrawerDiffContext";
import {
  ComponentOverridesSection,
  componentOverridesSchema,
} from "./ComponentOverridesSection";

type DeploymentComponent = NonNullable<
  GetDeploymentQuery["deployment"]
>["components"][number];

describe("componentOverridesSchema", () => {
  it("accepts an empty list", () => {
    const result = componentOverridesSchema.safeParse([]);
    expect(result.success).toBe(true);
  });

  it("accepts a per-component env-var override", () => {
    const result = componentOverridesSchema.safeParse([
      {
        name: "server",
        envVars: [{ name: "LOG_LEVEL", value: "debug" }],
      },
    ]);
    expect(result.success).toBe(true);
  });

  it("rejects an env-var name starting with a digit", () => {
    const result = componentOverridesSchema.safeParse([
      {
        name: "server",
        envVars: [{ name: "1BAD", value: "x" }],
      },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate component-override blocks", () => {
    const result = componentOverridesSchema.safeParse([
      { name: "server", envVars: [] },
      { name: "server", envVars: [] },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate env-var names within a component block", () => {
    const result = componentOverridesSchema.safeParse([
      {
        name: "server",
        envVars: [
          { name: "LOG_LEVEL", value: "debug" },
          { name: "LOG_LEVEL", value: "info" },
        ],
      },
    ]);
    expect(result.success).toBe(false);
  });
});

const COMPONENTS: DeploymentComponent[] = [
  { id: "c-server", name: "server", enabled: true, container: "server" },
  { id: "c-migrate", name: "migrate", enabled: true, container: null },
];

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
      <ComponentOverridesSection
        form={form}
        initial={initial}
        environment={{}}
        anchorId="componentOverrides"
        components={COMPONENTS}
      />
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
  const components = () =>
    (formApi!.state.values as UpdateDeploymentInput).components ?? [];
  return { components };
}

async function openComponent(name: string): Promise<void> {
  const trigger = screen.getByTestId(`component-override-trigger-${name}`);
  fireEvent.click(trigger);
  await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "true"));
}

describe("ComponentOverridesSection: components without a component container (FR-006)", () => {
  it("offers no env var editor and explains why", async () => {
    renderSection({ components: [{ name: "migrate", envVars: [] }] });

    await openComponent("migrate");

    expect(
      screen.getByTestId("comp-env-no-container-migrate"),
    ).toHaveTextContent(/declares no container for this component/i);
    expect(screen.queryByTestId("comp-env-add-migrate")).toBeNull();
    expect(screen.queryByTestId("comp-env-name-migrate-0")).toBeNull();
  });

  it("explains the restriction before an override block exists", async () => {
    renderSection();

    await openComponent("migrate");
    fireEvent.click(screen.getByTestId("component-override-add-migrate"));

    await screen.findByTestId("comp-env-no-container-migrate");
    expect(screen.queryByTestId("comp-env-add-migrate")).toBeNull();
  });

  it("shows stored env vars read-only, with a working remove control", async () => {
    const { components } = renderSection({
      components: [
        {
          name: "migrate",
          envVars: [
            { name: "LOG_LEVEL", value: "debug" },
            { name: "REGION", value: "eu" },
          ],
        },
      ],
    });

    await openComponent("migrate");

    const rows = screen.getAllByTestId("component-env-var-readonly-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("LOG_LEVEL");
    expect(rows[0]).toHaveTextContent("debug");
    expect(rows[1]).toHaveTextContent("REGION");
    // No editable inputs for the stored rows.
    expect(screen.queryByTestId("comp-env-name-migrate-0")).toBeNull();
    expect(screen.queryByTestId("comp-env-value-migrate-0")).toBeNull();
    expect(screen.queryByTestId("comp-env-add-migrate")).toBeNull();

    fireEvent.click(screen.getByTestId("comp-env-remove-migrate-0"));

    await waitFor(() =>
      expect(components()).toEqual([
        { name: "migrate", envVars: [{ name: "REGION", value: "eu" }] },
      ]),
    );
    expect(
      screen.getAllByTestId("component-env-var-readonly-row"),
    ).toHaveLength(1);
  });
});

describe("ComponentOverridesSection: components with a component container", () => {
  it("keeps the editable env var editor", async () => {
    const { components } = renderSection({
      components: [
        { name: "server", envVars: [{ name: "LOG_LEVEL", value: "debug" }] },
      ],
    });

    await openComponent("server");

    expect(screen.queryByTestId("comp-env-no-container-server")).toBeNull();
    expect(screen.queryByTestId("component-env-var-readonly-row")).toBeNull();
    expect(screen.getByTestId("comp-env-name-server-0")).toHaveValue(
      "LOG_LEVEL",
    );
    expect(screen.getByTestId("comp-env-value-server-0")).toHaveValue("debug");

    fireEvent.click(screen.getByTestId("comp-env-add-server"));
    const nameInput = await screen.findByTestId("comp-env-name-server-1");
    fireEvent.change(nameInput, { target: { value: "REGION" } });

    await waitFor(() =>
      expect(components()).toEqual([
        {
          name: "server",
          envVars: [
            { name: "LOG_LEVEL", value: "debug" },
            { name: "REGION", value: "" },
          ],
        },
      ]),
    );
  });
});
