import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { useForm, type AnyFormApi } from "@tanstack/react-form";

import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";

import { diff } from "@/lib/config-diff";
import { componentsFormToInput } from "@/lib/deployment-input";

import { DrawerDiffProvider } from "../../DrawerDiffContext";
import { DrawerFooter } from "../../DrawerFooter";
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

describe("componentOverridesSchema: image", () => {
  it.each([
    "registry.example/acme/app:1.0.0",
    "registry.example/acme/app:{{ app.version }}",
    "",
  ])("accepts %j", (image) => {
    const result = componentOverridesSchema.safeParse([
      { name: "server", envVars: [], image },
    ]);
    expect(result.success).toBe(true);
  });

  it.each([
    ["registry.example/acme/app", /no tag or digest/i],
    ["App:1", /not a valid image reference/i],
    ["app:{{ app.name }}", /only \{\{ app\.version \}\} is substituted/],
  ])("rejects %j", (image, message) => {
    const result = componentOverridesSchema.safeParse([
      { name: "server", envVars: [], image },
    ]);
    expect(result.success).toBe(false);
    expect(result.error?.issues[0].path).toEqual([0, "image"]);
    expect(result.error?.issues[0].message).toMatch(message);
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
  const components = () => values().components ?? [];
  return { components, values };
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

describe("ComponentOverridesSection: image override", () => {
  const IMAGE = "registry.example/acme/simple-app-patched:{{ app.version }}";

  it("offers an Image input with the token hint on a component with a container", async () => {
    renderSection({ components: [{ name: "server", envVars: [] }] });

    await openComponent("server");

    const input = screen.getByLabelText("Image for server");
    expect(input).toBe(screen.getByTestId("comp-image-server"));
    expect(input).toHaveValue("");
    expect(screen.getByTestId("comp-image-hint-server")).toHaveTextContent(
      "Use {{ app.version }} to follow the application version; a literal tag pins the image.",
    );
    expect(input).toHaveAccessibleDescription(/a literal tag pins the image/);
  });

  it("offers no Image input on a component without a container", async () => {
    renderSection({ components: [{ name: "migrate", envVars: [] }] });

    await openComponent("migrate");

    expect(screen.queryByTestId("comp-image-migrate")).toBeNull();
    expect(screen.queryByLabelText("Image for migrate")).toBeNull();
    expect(screen.queryByTestId("comp-image-readonly-migrate")).toBeNull();
  });

  it("shows a stored image read-only on a component without a container, with a working Remove", async () => {
    const stored = "registry.example/acme/migrate:1.0.0";
    const initial: UpdateDeploymentInput = {
      components: [{ name: "migrate", envVars: [], image: stored }],
    };
    const { components, values } = renderSection(initial);

    await openComponent("migrate");

    const row = screen.getByTestId("comp-image-readonly-migrate");
    expect(row).toHaveTextContent(stored);
    expect(
      screen.getByTestId("comp-image-not-applied-migrate"),
    ).toHaveTextContent(/^not applied$/);
    expect(
      screen.getByTestId("comp-image-no-container-migrate"),
    ).toHaveTextContent(
      "The driver declares no container for this component, so the image override can't be applied to it.",
    );
    expect(screen.queryByTestId("comp-image-migrate")).toBeNull();
    expect(screen.queryByLabelText("Image for migrate")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Remove image override for migrate" }),
    );

    await waitFor(() =>
      expect(components()).toEqual([
        { name: "migrate", envVars: [], image: null },
      ]),
    );
    expect(componentsFormToInput(components())).toEqual([
      { name: "migrate", envVars: [], image: null },
    ]);
    const entries = diff(initial, values(), []).entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      path: "components[migrate].image",
      kind: "remove",
      before: stored,
    });
    expect(screen.queryByTestId("comp-image-readonly-migrate")).toBeNull();
    expect(screen.queryByTestId("comp-image-migrate")).toBeNull();
    expect(
      screen.getByTestId("component-override-trigger-migrate"),
    ).not.toHaveTextContent("image");
  });

  it("accepts a valid reference and maps it into the submitted component block", async () => {
    const { components } = renderSection({
      components: [
        { name: "server", envVars: [{ name: "LOG_LEVEL", value: "debug" }] },
      ],
    });

    await openComponent("server");
    fireEvent.change(screen.getByTestId("comp-image-server"), {
      target: { value: IMAGE },
    });

    await waitFor(() =>
      expect(components()).toEqual([
        {
          name: "server",
          envVars: [{ name: "LOG_LEVEL", value: "debug" }],
          image: IMAGE,
        },
      ]),
    );
    expect(screen.queryByTestId("comp-image-error-server")).toBeNull();
    expect(componentsFormToInput(components())).toEqual([
      {
        name: "server",
        envVars: [{ name: "LOG_LEVEL", value: "debug" }],
        image: IMAGE,
      },
    ]);
    expect(
      screen.getByTestId("component-override-trigger-server"),
    ).toHaveTextContent("1 env var · image");
  });

  it("shows an inline error for an invalid reference and blocks Review & apply", async () => {
    renderSection({ components: [{ name: "server", envVars: [] }] });

    await openComponent("server");
    fireEvent.change(screen.getByTestId("comp-image-server"), {
      target: { value: "registry.example/acme/app" },
    });

    expect(
      await screen.findByTestId("comp-image-error-server"),
    ).toHaveTextContent(/no tag or digest/i);
    const apply = screen.getByTestId("drawer-review-apply-button");
    expect(apply).toBeDisabled();
    expect(apply).toHaveAccessibleDescription(
      "Fix the invalid image reference on server before applying.",
    );

    // Re-query: the changed-field frame remounts the input.
    fireEvent.change(screen.getByTestId("comp-image-server"), {
      target: { value: IMAGE },
    });

    await waitFor(() => expect(apply).toBeEnabled());
    expect(screen.queryByTestId("comp-image-error-server")).toBeNull();
    expect(screen.queryByTestId("drawer-invalid-hint")).toBeNull();
  });

  it("unblocks Review & apply once the block carrying an invalid reference is removed", async () => {
    renderSection({
      components: [{ name: "server", envVars: [], image: IMAGE }],
    });

    await openComponent("server");
    fireEvent.change(screen.getByTestId("comp-image-server"), {
      target: { value: "App:1" },
    });
    const apply = screen.getByTestId("drawer-review-apply-button");
    await waitFor(() => expect(apply).toBeDisabled());

    fireEvent.click(screen.getByTestId("component-override-remove-server"));

    await waitFor(() => expect(apply).toBeEnabled());
    expect(screen.queryByTestId("drawer-invalid-hint")).toBeNull();
  });

  it("clearing a stored image submits image: null and drops it from the summary", async () => {
    const { components } = renderSection({
      components: [{ name: "server", envVars: [], image: IMAGE }],
    });

    await openComponent("server");
    fireEvent.change(screen.getByTestId("comp-image-server"), {
      target: { value: "" },
    });

    await waitFor(() =>
      expect(components()).toEqual([
        { name: "server", envVars: [], image: "" },
      ]),
    );
    expect(componentsFormToInput(components())).toEqual([
      { name: "server", envVars: [], image: null },
    ]);
    expect(screen.queryByTestId("comp-image-error-server")).toBeNull();
    const editor = screen.getByTestId("component-image-editor-server");
    expect(editor.closest("[data-testid=changed-field-frame]")).not.toBeNull();
    const trigger = screen.getByTestId("component-override-trigger-server");
    expect(trigger).toHaveTextContent("override (empty)");
    expect(trigger).not.toHaveTextContent("image");
  });

  it("pre-fills a stored image", async () => {
    renderSection({
      components: [{ name: "server", envVars: [], image: IMAGE }],
    });

    await openComponent("server");

    expect(screen.getByTestId("comp-image-server")).toHaveValue(IMAGE);
    expect(
      screen.getByTestId("component-override-trigger-server"),
    ).toHaveTextContent("image");
  });
});

describe("ComponentOverridesSection: orphaned override blocks", () => {
  it("removes an orphaned block, image override included, as a whole", async () => {
    const initial: UpdateDeploymentInput = {
      components: [
        { name: "legacy", envVars: [], image: "registry.example/acme/x:1.0" },
      ],
    };
    const { components, values } = renderSection(initial);

    const orphan = screen.getByTestId("component-override-orphan");
    expect(orphan).toHaveAttribute("data-component", "legacy");
    expect(screen.queryByTestId("comp-image-legacy")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Remove orphaned override legacy" }),
    );

    await waitFor(() => expect(components()).toEqual([]));
    expect(diff(initial, values(), []).entries).toEqual([
      expect.objectContaining({ path: "components[legacy]", kind: "remove" }),
    ]);
  });
});
