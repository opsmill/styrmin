import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { useForm, type AnyFormApi } from "@tanstack/react-form";

import type {
  GetDeploymentQuery,
  UpdateDeploymentInput,
} from "@/generated/graphql";

import { diff } from "@/lib/config-diff";
import type { DriverParameterSchema } from "@/lib/configuration-types";
import { componentsFormToInput } from "@/lib/deployment-input";

import { DrawerDiffProvider } from "../../DrawerDiffContext";
import { DrawerFooter } from "../../DrawerFooter";
import {
  ComponentOverridesSection,
  componentOverridesSchema,
} from "./ComponentOverridesSection";

type Deployment = NonNullable<GetDeploymentQuery["deployment"]>;
type DeploymentComponent = Deployment["components"][number];
type ReplicaRow = Deployment["componentReplicas"][number];
type DriverComponentConfig =
  Deployment["applicationDriverVersion"]["componentConfigs"][number];

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
  { id: "c-database", name: "database", enabled: true, container: "postgres" },
];

function replicaRow(
  component: string,
  fields: Partial<ReplicaRow> = {},
): ReplicaRow {
  return {
    component,
    count: null,
    source: "CHART",
    override: null,
    singleton: false,
    isOrphaned: false,
    isApplicable: true,
    ...fields,
  };
}

// server: driver default 2; migrate: chart; database: singleton.
const REPLICAS: ReplicaRow[] = [
  replicaRow("database", {
    count: 1,
    source: "DRIVER_DEFAULT",
    singleton: true,
  }),
  replicaRow("migrate"),
  replicaRow("server", { count: 2, source: "DRIVER_DEFAULT" }),
];

const DRIVER_COMPONENTS: DriverComponentConfig[] = [
  { name: "server", replicas: 2 },
  { name: "migrate", replicas: null },
  { name: "database", replicas: null },
];

/** Mount the section against a real TanStack Form, as `ConfigEditDrawer` does. */
function Harness({
  initial,
  publish,
  replicas,
  driverParameters,
}: {
  initial: UpdateDeploymentInput;
  publish: (form: AnyFormApi) => void;
  replicas: ReplicaRow[];
  driverParameters?: DriverParameterSchema;
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
        componentReplicas={replicas}
        driverComponentConfigs={DRIVER_COMPONENTS}
        driverParameters={driverParameters}
      />
      <DrawerFooter onDiscard={() => {}} onReviewApply={() => {}} />
    </DrawerDiffProvider>
  );
}

function renderSection(
  initial: UpdateDeploymentInput = {},
  replicas: ReplicaRow[] = REPLICAS,
  driverParameters?: DriverParameterSchema,
) {
  let formApi: AnyFormApi | undefined;
  render(
    <Harness
      initial={initial}
      replicas={replicas}
      driverParameters={driverParameters}
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

  it("explains the restriction instead of offering Add override", async () => {
    const { components } = renderSection();

    await openComponent("migrate");

    expect(
      screen.getByTestId("component-override-no-container-migrate"),
    ).toHaveTextContent(
      "The driver declares no container for this component, so env var, image, command and args overrides can't be applied to it.",
    );
    expect(screen.queryByTestId("component-override-add-migrate")).toBeNull();
    expect(components()).toEqual([]);
  });

  it("marks the collapsed row not applied when it stores values", () => {
    renderSection({
      components: [
        { name: "migrate", envVars: [], args: ["--all"] },
        { name: "server", envVars: [], args: ["-v"] },
      ],
    });

    expect(
      screen.getByTestId("component-override-not-applied-migrate"),
    ).toHaveTextContent(/^not applied$/);
    expect(
      screen.queryByTestId("component-override-not-applied-server"),
    ).toBeNull();
  });

  it("does not mark an empty block not applied", () => {
    renderSection({ components: [{ name: "migrate", envVars: [] }] });

    expect(
      screen.queryByTestId("component-override-not-applied-migrate"),
    ).toBeNull();
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

describe("ComponentOverridesSection: command and args without a component container (FR-008)", () => {
  const COMMAND = ["/bin/sh", "-c"];
  const ARGS = ["migrate", "--all"];

  it("offers no Command or Args editor", async () => {
    renderSection({ components: [{ name: "migrate", envVars: [] }] });

    await openComponent("migrate");

    expect(screen.queryByTestId("component-command-editor-migrate")).toBeNull();
    expect(screen.queryByTestId("component-args-editor-migrate")).toBeNull();
    expect(screen.queryByTestId("comp-command-add-migrate")).toBeNull();
    expect(screen.queryByTestId("comp-args-add-migrate")).toBeNull();
    expect(screen.queryByTestId("comp-command-readonly-migrate")).toBeNull();
    expect(screen.queryByTestId("comp-args-readonly-migrate")).toBeNull();
  });

  it("shows a stored command and args read-only with a not applied badge", async () => {
    renderSection({
      components: [
        { name: "migrate", envVars: [], command: COMMAND, args: ARGS },
      ],
    });

    await openComponent("migrate");

    expect(
      screen.getByTestId("comp-command-readonly-value-migrate"),
    ).toHaveTextContent('["/bin/sh","-c"]');
    expect(
      screen.getByTestId("comp-args-readonly-value-migrate"),
    ).toHaveTextContent('["migrate","--all"]');
    for (const field of ["command", "args"]) {
      expect(
        screen.getByTestId(`comp-${field}-not-applied-migrate`),
      ).toHaveTextContent(/^not applied$/);
      expect(
        screen.getByTestId(`comp-${field}-no-container-migrate`),
      ).toHaveTextContent(
        `The driver declares no container for this component, so the ${field} override can't be applied to it. It can only be removed.`,
      );
    }
    expect(screen.queryByTestId("comp-command-migrate-0")).toBeNull();
    expect(screen.queryByTestId("comp-args-migrate-0")).toBeNull();
    expect(screen.queryByTestId("comp-command-add-migrate")).toBeNull();
    expect(screen.queryByTestId("comp-args-add-migrate")).toBeNull();
  });

  it("shows list boundaries and empty elements in read-only values", async () => {
    renderSection({
      components: [
        {
          name: "migrate",
          envVars: [],
          command: ["a b"],
          args: ["a", "", "b"],
        },
      ],
    });

    await openComponent("migrate");

    expect(
      screen.getByTestId("comp-command-readonly-value-migrate"),
    ).toHaveTextContent('["a b"]');
    expect(
      screen.getByTestId("comp-args-readonly-value-migrate"),
    ).toHaveTextContent('["a","","b"]');
  });

  it("Remove clears the stored command, then args, on submit", async () => {
    const initial: UpdateDeploymentInput = {
      components: [
        { name: "migrate", envVars: [], command: COMMAND, args: ARGS },
      ],
    };
    const { components, values } = renderSection(initial);
    const apply = screen.getByTestId("drawer-review-apply-button");
    expect(apply).toBeDisabled();

    await openComponent("migrate");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove command override for migrate",
      }),
    );

    await waitFor(() =>
      expect(components()).toEqual([
        { name: "migrate", envVars: [], command: [], args: ARGS },
      ]),
    );
    expect(componentsFormToInput(components())).toEqual([
      { name: "migrate", envVars: [], args: ARGS },
    ]);
    expect(diff(initial, values(), []).entries).toEqual([
      expect.objectContaining({
        path: "components[migrate].command",
        kind: "remove",
        before: JSON.stringify(COMMAND),
      }),
    ]);
    await waitFor(() => expect(apply).toBeEnabled());
    expect(screen.queryByTestId("comp-command-readonly-migrate")).toBeNull();
    expect(screen.getByTestId("comp-args-readonly-migrate")).toBeVisible();
    expect(
      screen.getByTestId("component-override-trigger-migrate"),
    ).not.toHaveTextContent("command");

    fireEvent.click(
      screen.getByRole("button", { name: "Remove args override for migrate" }),
    );

    await waitFor(() =>
      expect(componentsFormToInput(components())).toEqual([
        { name: "migrate", envVars: [] },
      ]),
    );
    expect(screen.queryByTestId("comp-args-readonly-migrate")).toBeNull();
    expect(screen.queryByTestId("component-command-editor-migrate")).toBeNull();
    expect(screen.queryByTestId("component-args-editor-migrate")).toBeNull();
  });

  it("keeps the Command and Args editors on a component with a container", async () => {
    const initial: UpdateDeploymentInput = {
      components: [
        { name: "server", envVars: [], command: ["/bin/sh"], args: ["-v"] },
      ],
    };
    const { components, values } = renderSection(initial);

    await openComponent("server");

    expect(screen.getByTestId("component-command-editor-server")).toBeVisible();
    expect(screen.getByTestId("component-args-editor-server")).toBeVisible();
    expect(screen.getByTestId("comp-command-server-0")).toHaveValue("/bin/sh");
    expect(screen.getByTestId("comp-args-server-0")).toHaveValue("-v");
    expect(screen.queryByTestId("comp-command-readonly-server")).toBeNull();
    expect(screen.queryByTestId("comp-args-readonly-server")).toBeNull();

    fireEvent.change(screen.getByTestId("comp-args-server-0"), {
      target: { value: "--verbose" },
    });

    await waitFor(() =>
      expect(components()).toEqual([
        {
          name: "server",
          envVars: [],
          command: ["/bin/sh"],
          args: ["--verbose"],
        },
      ]),
    );
    expect(diff(initial, values(), []).entries).toEqual([
      expect.objectContaining({
        path: "components[server].args",
        kind: "change",
        before: JSON.stringify(["-v"]),
        after: JSON.stringify(["--verbose"]),
      }),
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("drawer-review-apply-button")).toBeEnabled(),
    );
  });
});

describe("ComponentOverridesSection: Command and Args editors", () => {
  it("explains each editor and its empty state", async () => {
    renderSection({ components: [{ name: "server", envVars: [] }] });

    await openComponent("server");

    expect(
      screen.getByRole("group", { name: "Command" }),
    ).toHaveAccessibleDescription(
      "Replaces the whole command list of the container, its entrypoint. Enter one list element per row.",
    );
    expect(
      screen.getByRole("group", { name: "Args" }),
    ).toHaveAccessibleDescription(
      "Replaces the whole args list of the container. Enter one list element per row.",
    );
    expect(screen.getByTestId("comp-command-empty-server")).toHaveTextContent(
      "No command override: the container keeps the command the chart renders.",
    );
    expect(screen.getByTestId("comp-args-empty-server")).toHaveTextContent(
      "No args override: the container keeps the args the chart renders.",
    );
  });

  it("names each input for assistive technology", async () => {
    renderSection({
      components: [
        {
          name: "server",
          envVars: [],
          command: ["/bin/sh", "-c"],
          args: ["-v"],
        },
      ],
    });

    await openComponent("server");

    expect(
      screen.getByRole("textbox", { name: "Command element 2 for server" }),
    ).toHaveValue("-c");
    expect(
      screen.getByRole("textbox", { name: "Args element 1 for server" }),
    ).toHaveValue("-v");
  });

  it("warns about an empty command element until it has a value", async () => {
    renderSection({ components: [{ name: "server", envVars: [] }] });

    await openComponent("server");
    fireEvent.click(screen.getByTestId("comp-command-add-server"));
    fireEvent.click(screen.getByTestId("comp-args-add-server"));

    const warning = await screen.findByTestId(
      "comp-command-empty-warning-server-0",
    );
    expect(warning).toHaveTextContent(
      "This element is empty. The container receives it as an empty string.",
    );
    expect(screen.queryByTestId("comp-args-empty-warning-server-0")).toBeNull();

    fireEvent.change(screen.getByTestId("comp-command-server-0"), {
      target: { value: "/bin/sh" },
    });

    await waitFor(() =>
      expect(
        screen.queryByTestId("comp-command-empty-warning-server-0"),
      ).toBeNull(),
    );
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
      expect.objectContaining({
        path: "components[legacy].image",
        kind: "remove",
      }),
    ]);
  });
});

describe("ComponentOverridesSection: replicas (023)", () => {
  const BELOW_ONE = "Must be 1 or more. To run no pods, stop the component.";

  it("renders a Replicas field on every component, container or not", async () => {
    const { components } = renderSection();

    await openComponent("server");
    await openComponent("migrate");

    const server = screen.getByRole("spinbutton", {
      name: "Replicas for server",
    });
    expect(server).toBe(screen.getByTestId("comp-replicas-server"));
    expect(server).toHaveValue(null);
    expect(
      screen.getByRole("spinbutton", { name: "Replicas for migrate" }),
    ).toBe(screen.getByTestId("comp-replicas-migrate"));
    expect(components()).toEqual([]);
  });

  it("shows the value that applies without an override as the placeholder", async () => {
    renderSection();

    await openComponent("server");
    await openComponent("migrate");

    expect(screen.getByTestId("comp-replicas-server")).toHaveAttribute(
      "placeholder",
      "2 (driver default)",
    );
    expect(screen.getByTestId("comp-replicas-migrate")).toHaveAttribute(
      "placeholder",
      "set by the chart",
    );
  });

  it("creates a block holding only the count on a component without a block", async () => {
    const initial: UpdateDeploymentInput = {};
    const { components, values } = renderSection(initial);

    await openComponent("migrate");
    fireEvent.change(screen.getByTestId("comp-replicas-migrate"), {
      target: { value: "3" },
    });

    await waitFor(() =>
      expect(components()).toEqual([{ name: "migrate", replicas: 3 }]),
    );
    expect(componentsFormToInput(components())).toEqual([
      { name: "migrate", replicas: 3 },
    ]);
    expect(diff(initial, values(), []).entries).toEqual([
      expect.objectContaining({
        path: "components[migrate].replicas",
        kind: "add",
        after: "3",
      }),
    ]);
    expect(screen.getByTestId("comp-replicas-migrate")).toHaveValue(3);
    expect(
      screen.getByTestId("component-override-trigger-migrate"),
    ).toHaveTextContent("replicas: 3");
    expect(
      screen.queryByTestId("component-override-not-applied-migrate"),
    ).toBeNull();
  });

  it.each(["server", "migrate"])(
    "keeps the Replicas input on %s, which has no block, focused while typing",
    async (name) => {
      const user = userEvent.setup();
      const { components } = renderSection();

      await openComponent(name);
      const input = screen.getByTestId(`comp-replicas-${name}`);
      await user.type(input, "12");

      expect(screen.getByTestId(`comp-replicas-${name}`)).toBe(input);
      expect(input).toHaveFocus();
      expect(input).toHaveValue(12);
      expect(components()).toEqual([{ name, replicas: 12 }]);
      expect(componentsFormToInput(components())).toEqual([
        { name, replicas: 12 },
      ]);
    },
  );

  it("removes the block again when a new count is cleared", async () => {
    const user = userEvent.setup();
    const { components, values } = renderSection({});

    await openComponent("server");
    const input = screen.getByTestId("comp-replicas-server");
    await user.type(input, "3");
    expect(components()).toEqual([{ name: "server", replicas: 3 }]);

    await user.clear(input);

    expect(components()).toEqual([]);
    expect(diff({}, values(), []).entries).toEqual([]);
    expect(screen.getByTestId("comp-replicas-server")).toBe(input);
    expect(input).toHaveFocus();
    expect(
      screen.getByTestId("component-override-trigger-server"),
    ).not.toHaveTextContent("override (empty)");
    expect(screen.getByTestId("drawer-review-apply-button")).toBeDisabled();
  });

  it("keeps a block that holds other overrides when its new count is cleared", async () => {
    const user = userEvent.setup();
    const initial: UpdateDeploymentInput = {};
    const { components } = renderSection(initial);

    await openComponent("server");
    const input = screen.getByTestId("comp-replicas-server");
    await user.type(input, "3");
    fireEvent.change(screen.getByTestId("comp-image-server"), {
      target: { value: "registry.example/acme/app:1.0" },
    });
    await user.clear(screen.getByTestId("comp-replicas-server"));

    await waitFor(() =>
      expect(components()).toEqual([
        expect.objectContaining({
          name: "server",
          image: "registry.example/acme/app:1.0",
          replicas: undefined,
        }),
      ]),
    );
  });

  it("names a driver parameter that sets the same count", async () => {
    renderSection({}, REPLICAS, [
      {
        name: "replicas_server",
        label: "Number of server replicas",
        kind: "integer",
        default: null,
        values: null,
      },
    ]);

    await openComponent("server");
    await openComponent("migrate");

    expect(screen.getByTestId("comp-replicas-hint-server")).toHaveTextContent(
      "The driver parameter “Number of server replicas” also sets this count. When both are set, this override applies.",
    );
    expect(screen.getByTestId("comp-replicas-hint-migrate")).toHaveTextContent(
      /^Leave empty for no override\.$/,
    );
  });

  it("keeps the Replicas input of an existing block focused while typing", async () => {
    const user = userEvent.setup();
    const { components } = renderSection({
      components: [{ name: "server", envVars: [] }],
    });

    await openComponent("server");
    const input = screen.getByTestId("comp-replicas-server");
    await user.type(input, "12");

    expect(screen.getByTestId("comp-replicas-server")).toBe(input);
    expect(input).toHaveFocus();
    expect(components()).toEqual([
      { name: "server", envVars: [], replicas: 12 },
    ]);
  });

  it.each(["0", "1.5", "2147483648"])(
    "blocks Review & apply while a count of %s is in the field",
    async (typed) => {
      renderSection();

      await openComponent("migrate");
      fireEvent.change(screen.getByTestId("comp-replicas-migrate"), {
        target: { value: typed },
      });

      const apply = screen.getByTestId("drawer-review-apply-button");
      await waitFor(() => expect(apply).toBeDisabled());
      expect(apply).toHaveAccessibleDescription(
        "Fix the invalid replica count on migrate before applying.",
      );

      fireEvent.change(screen.getByTestId("comp-replicas-migrate"), {
        target: { value: "2" },
      });

      await waitFor(() => expect(apply).toBeEnabled());
      expect(screen.queryByTestId("drawer-invalid-hint")).toBeNull();
    },
  );

  it("pre-fills a stored override and clearing it submits replicas: null", async () => {
    const initial: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [], replicas: 3 }],
    };
    const { components, values } = renderSection(initial, [
      replicaRow("database", {
        count: 1,
        source: "DRIVER_DEFAULT",
        singleton: true,
      }),
      replicaRow("migrate"),
      replicaRow("server", { count: 3, source: "OVERRIDE", override: 3 }),
    ]);

    await openComponent("server");
    expect(screen.getByTestId("comp-replicas-server")).toHaveValue(3);

    fireEvent.change(screen.getByTestId("comp-replicas-server"), {
      target: { value: "" },
    });

    await waitFor(() =>
      expect(components()).toEqual([
        { name: "server", envVars: [], replicas: null },
      ]),
    );
    // Without the override the driver default applies again.
    expect(screen.getByTestId("comp-replicas-server")).toHaveAttribute(
      "placeholder",
      "2 (driver default)",
    );
    expect(componentsFormToInput(components())).toEqual([
      { name: "server", envVars: [], replicas: null },
    ]);
    expect(diff(initial, values(), []).entries).toEqual([
      expect.objectContaining({
        path: "components[server].replicas",
        kind: "remove",
        before: "3",
      }),
    ]);
  });

  it("changes a stored override with a replicas diff entry", async () => {
    const initial: UpdateDeploymentInput = {
      components: [{ name: "server", envVars: [], replicas: 2 }],
    };
    const { components, values } = renderSection(initial);

    await openComponent("server");
    fireEvent.change(screen.getByTestId("comp-replicas-server"), {
      target: { value: "4" },
    });

    await waitFor(() =>
      expect(components()).toEqual([
        { name: "server", envVars: [], replicas: 4 },
      ]),
    );
    expect(diff(initial, values(), []).entries).toEqual([
      expect.objectContaining({
        path: "components[server].replicas",
        kind: "change",
        before: "2",
        after: "4",
      }),
    ]);
  });

  it.each(["0", "-1"])(
    "shows the stop-the-component error for %s",
    async (typed) => {
      renderSection({ components: [{ name: "server", envVars: [] }] });

      await openComponent("server");
      fireEvent.change(screen.getByTestId("comp-replicas-server"), {
        target: { value: typed },
      });

      const error = await screen.findByTestId("comp-replicas-error-server");
      expect(error).toHaveTextContent(BELOW_ONE);
      const input = screen.getByTestId("comp-replicas-server");
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input).toHaveAccessibleDescription(new RegExp(BELOW_ONE));

      fireEvent.change(screen.getByTestId("comp-replicas-server"), {
        target: { value: "2" },
      });
      await waitFor(() =>
        expect(screen.queryByTestId("comp-replicas-error-server")).toBeNull(),
      );
    },
  );

  it("shows a singleton component as a read-only 1 (singleton) field", async () => {
    const { components } = renderSection();

    await openComponent("database");

    const field = screen.getByRole("textbox", {
      name: "Replicas for database",
    });
    expect(field).toBe(screen.getByTestId("comp-replicas-database"));
    expect(field).toHaveValue("1 (singleton)");
    expect(field).toHaveAttribute("readonly");
    expect(field).toHaveAccessibleDescription(
      "The driver marks this component as a singleton, so it runs 1 pod.",
    );
    fireEvent.change(field, { target: { value: "2" } });
    expect(components()).toEqual([]);
    expect(screen.queryByTestId("comp-replicas-readonly-database")).toBeNull();
  });

  it("lets a stored override above 1 on a singleton only be removed", async () => {
    const initial: UpdateDeploymentInput = {
      components: [{ name: "database", envVars: [], replicas: 3 }],
    };
    const { components, values } = renderSection(initial, [
      replicaRow("database", {
        count: 1,
        source: "DRIVER_DEFAULT",
        override: 3,
        singleton: true,
      }),
      replicaRow("migrate"),
      replicaRow("server", { count: 2, source: "DRIVER_DEFAULT" }),
    ]);

    expect(
      screen.getByTestId("component-override-not-applied-database"),
    ).toHaveTextContent(/^not applied$/);
    await openComponent("database");

    expect(screen.getByTestId("comp-replicas-database")).toHaveValue(
      "1 (singleton)",
    );
    const row = screen.getByTestId("comp-replicas-readonly-database");
    expect(row).toHaveTextContent("3");
    expect(row).toHaveTextContent("not applied");
    expect(
      screen.getByTestId("comp-replicas-singleton-note-database"),
    ).toHaveTextContent(
      "The driver marks this component as a singleton, so the stored override of 3 can't be applied. It can only be removed.",
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove replica override for database",
      }),
    );

    await waitFor(() =>
      expect(components()).toEqual([
        { name: "database", envVars: [], replicas: null },
      ]),
    );
    expect(componentsFormToInput(components())).toEqual([
      { name: "database", envVars: [], replicas: null },
    ]);
    expect(diff(initial, values(), []).entries).toEqual([
      expect.objectContaining({
        path: "components[database].replicas",
        kind: "remove",
        before: "3",
      }),
    ]);
    expect(screen.queryByTestId("comp-replicas-readonly-database")).toBeNull();
    expect(screen.getByTestId("comp-replicas-database")).toHaveValue(
      "1 (singleton)",
    );
    expect(
      screen.queryByTestId("component-override-not-applied-database"),
    ).toBeNull();
  });

  it("no longer lists replicas among the future per-component fields", async () => {
    renderSection({ components: [{ name: "server", envVars: [] }] });

    await openComponent("server");

    const note = screen.getByTestId("component-override-future-placeholder");
    expect(note).toHaveTextContent(
      "More per-component fields (CPU / memory requests & limits) are coming in future iterations.",
    );
    expect(note).not.toHaveTextContent(/replicas/i);
  });
});
