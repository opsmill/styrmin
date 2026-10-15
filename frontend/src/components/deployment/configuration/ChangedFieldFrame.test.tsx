import { describe, it, expect } from "vitest";
import { useForm } from "@tanstack/react-form";
import { render, screen, userEvent } from "@/test/utils";
import { ChangedFieldFrame } from "./ChangedFieldFrame";

interface HarnessProps {
  initialValue: string;
  /** Value to pass as the `initial` prop — what the frame compares the live value against. */
  initialProp: unknown;
  /** Value to pass as the `environment` prop. */
  environmentProp: unknown;
}

function Harness({ initialValue, initialProp, environmentProp }: HarnessProps) {
  const form = useForm({
    defaultValues: { cpu: initialValue },
  });
  return (
    <form>
      <ChangedFieldFrame
        name="cpu"
        form={form}
        initial={initialProp}
        environment={environmentProp}
      >
        <form.Field name="cpu">
          {(field) => (
            <input
              data-testid="cpu-input"
              aria-label="cpu"
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
            />
          )}
        </form.Field>
      </ChangedFieldFrame>
    </form>
  );
}

describe("ChangedFieldFrame", () => {
  it("renders children without decoration when the value matches initial", async () => {
    await render(
      <Harness initialValue="100m" initialProp="100m" environmentProp="100m" />,
    );

    expect(screen.queryByTestId("changed-field-frame")).not.toBeInTheDocument();
    expect(screen.queryByTestId("changed-pill")).not.toBeInTheDocument();
    expect(screen.queryByTestId("changed-from")).not.toBeInTheDocument();
    expect(screen.getByTestId("cpu-input")).toBeInTheDocument();
  });

  it('renders the amber frame, "changed" pill, and "from X" annotation when the value differs from initial', async () => {
    const user = userEvent.setup();
    await render(
      <Harness
        initialValue="100m"
        initialProp="100m"
        // Different from initial so the "(env)" suffix is omitted.
        environmentProp="50m"
      />,
    );

    const input = screen.getByTestId("cpu-input");
    await user.clear(input);
    await user.type(input, "200m");

    expect(screen.getByTestId("changed-field-frame")).toBeInTheDocument();
    expect(screen.getByTestId("changed-pill")).toHaveTextContent(/changed/i);
    expect(screen.getByTestId("changed-from")).toHaveTextContent("from 100m");
    expect(screen.getByTestId("changed-from")).not.toHaveTextContent("(env)");
  });

  it("keeps the input mounted and focused when the value starts to differ", async () => {
    const user = userEvent.setup();
    await render(<Harness initialValue="" initialProp="" environmentProp="" />);

    const input = screen.getByTestId("cpu-input");
    await user.type(input, "250m");

    expect(screen.getByTestId("changed-field-frame")).toBeInTheDocument();
    expect(screen.getByTestId("cpu-input")).toBe(input);
    expect(input).toHaveFocus();
    expect(input).toHaveValue("250m");
  });

  it('renders the "(env)" suffix when the original value came from the environment', async () => {
    const user = userEvent.setup();
    await render(
      <Harness
        initialValue="100m"
        // initial === environment → the original was inherited.
        initialProp="100m"
        environmentProp="100m"
      />,
    );

    const input = screen.getByTestId("cpu-input");
    await user.clear(input);
    await user.type(input, "250m");

    expect(screen.getByTestId("changed-field-frame")).toBeInTheDocument();
    const annotation = screen.getByTestId("changed-from");
    expect(annotation).toHaveTextContent("from 100m (env)");
  });
});
