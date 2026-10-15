/**
 * Deployment-scope backup retention editor (016-backup-retention-ttl).
 *
 * The backend accepted `DeploymentConfigInput.backupTtl` and the diff/impact
 * libraries already knew about it, but no UI could set it — a deployment could
 * only ever take its environment's policy.
 */
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { useForm, type AnyFormApi } from "@tanstack/react-form";

import type { UpdateDeploymentInput } from "@/generated/graphql";
import { MAX_BACKUP_TTL_HOURS } from "@/lib/backup-ttl";

import { DrawerDiffProvider } from "../../DrawerDiffContext";
import { StorageRuntimeSection } from "./StorageRuntimeSection";

/**
 * Mount the section against a real TanStack Form, mirroring how
 * `ConfigEditDrawer` wires it: one form store seeded with `initial`, a
 * `DrawerDiffProvider` over the same snapshot, and the environment projection
 * passed separately.
 *
 * `publish` hands the form instance to the test so it can read the live store
 * and assert what would be submitted — including the difference between
 * `undefined` (key dropped) and `""` (an invalid explicit value).
 */
function Harness({
  initial,
  environment,
  publish,
}: {
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  publish: (form: AnyFormApi) => void;
}) {
  const form = useForm({ defaultValues: initial });
  // Publish from an effect rather than during render. The form store is live,
  // so reading `form.state.values` at assertion time always sees the current
  // value without the harness having to re-render.
  useEffect(() => {
    publish(form);
  }, [form, publish]);
  return (
    <DrawerDiffProvider form={form} initialValues={initial} driverSchema={[]}>
      <StorageRuntimeSection
        form={form}
        initial={initial}
        environment={environment}
        anchorId="storageRuntime"
      />
    </DrawerDiffProvider>
  );
}

function renderSection(
  initial: UpdateDeploymentInput = {},
  environment: UpdateDeploymentInput = {},
) {
  let formApi: AnyFormApi | undefined;
  render(
    <Harness
      initial={initial}
      environment={environment}
      publish={(form) => {
        formApi = form;
      }}
    />,
  );
  /** Current value of `backupTtl` in the live form store. */
  const backupTtl = () =>
    (formApi!.state.values as UpdateDeploymentInput).backupTtl;
  return { backupTtl };
}

const input = () => screen.getByTestId("storage-backup-ttl-input");

/** Set the field in one change event, as a paste or an autofill does. */
function setTtl(value: string): void {
  fireEvent.change(input(), { target: { value } });
}

describe("StorageRuntimeSection: deployment-scope backup retention", () => {
  it("renders under the storageRuntime anchor so the nav rail can reach it", () => {
    renderSection();

    const section = document.querySelector('[data-section="storageRuntime"]');
    expect(section).not.toBeNull();
    expect(section).toHaveAttribute("id", "storageRuntime-anchor");
  });

  it("SET: applies a retention to a deployment that had none", async () => {
    const { backupTtl } = renderSection({}, { backupTtl: "720h" });

    setTtl("2160h");

    await waitFor(() => expect(backupTtl()).toBe("2160h"));
  });

  it("SET: overwrites an existing deployment-level policy", async () => {
    const { backupTtl } = renderSection(
      { backupTtl: "2160h" },
      { backupTtl: "720h" },
    );

    expect(input()).toHaveValue("2160h");
    setTtl("8760h");

    await waitFor(() => expect(backupTtl()).toBe("8760h"));
  });

  it("CLEAR: emptying the field yields undefined, not an empty string", async () => {
    // This is the whole "revert to inherited" gesture: `undefined` drops the
    // key from the full-replacement input, so the backend re-resolves from the
    // environment. `""` would be sent as an explicit — and invalid — value.
    const { backupTtl } = renderSection(
      { backupTtl: "2160h" },
      { backupTtl: "720h" },
    );

    setTtl("");

    await waitFor(() => expect(backupTtl()).toBeUndefined());
    expect(backupTtl()).not.toBe("");
    // Clearing is not an error state.
    expect(screen.queryByTestId("storage-backup-ttl-error")).toBeNull();
  });

  it("CLEAR: the hint names the environment value that would take over", () => {
    renderSection({ backupTtl: "2160h" }, { backupTtl: "720h" });

    expect(screen.getByTestId("storage-backup-ttl-hint").textContent).toContain(
      "the environment's 720h",
    );
  });

  it("CLEAR: the hint names the built-in default when the environment sets none", () => {
    renderSection({ backupTtl: "2160h" }, {});

    const hint = screen.getByTestId("storage-backup-ttl-hint").textContent;
    expect(hint).toContain("shallower scope");
    expect(hint).toContain("720h");
  });

  it("INVALID: rejects a day unit, which Go cannot parse", async () => {
    renderSection({}, {});

    setTtl("30d");

    const error = await screen.findByTestId("storage-backup-ttl-error");
    expect(error.textContent).toMatch(/positive Go duration using h\/m\/s/i);
  });

  it("INVALID: rejects a value above the Go int64-nanosecond ceiling", async () => {
    renderSection({}, {});

    setTtl(`${MAX_BACKUP_TTL_HOURS + 1}h`);

    const error = await screen.findByTestId("storage-backup-ttl-error");
    expect(error.textContent).toMatch(/must not exceed/i);
  });

  it("INVALID: rejects an all-zero duration that expresses no retention", async () => {
    // `0h` matches the syntax but Velero would read it as "keep forever".
    renderSection({}, {});

    setTtl("0h");

    expect(
      await screen.findByTestId("storage-backup-ttl-error"),
    ).toBeInTheDocument();
  });

  it("VALID: accepts a compound duration without complaint", async () => {
    const { backupTtl } = renderSection({}, {});

    setTtl("1h30m");

    await waitFor(() => expect(backupTtl()).toBe("1h30m"));
    expect(screen.queryByTestId("storage-backup-ttl-error")).toBeNull();
  });

  it("INHERITANCE: marks the field changed and names the env origin", async () => {
    // `initial === environment` means the deployment was inheriting, so editing
    // it must read as "changed from 720h (env)" rather than a bare override.
    renderSection({ backupTtl: "720h" }, { backupTtl: "720h" });

    setTtl("2160h");

    await waitFor(() =>
      expect(screen.getByTestId("changed-field-frame")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("changed-from").textContent).toContain("(env)");
    expect(screen.getByTestId("changed-from").textContent).toContain("720h");
  });

  it("counts the retention edit against the storageRuntime section chip", async () => {
    // Proves the shared drawer diff attributes the change to this section, so
    // the nav rail's change dot lights up on the section the operator edited.
    renderSection({ backupTtl: "720h" }, {});

    setTtl("336h");

    await waitFor(() =>
      expect(
        screen.getByTestId("section-changed-chip-storageRuntime"),
      ).toBeInTheDocument(),
    );
  });
});
