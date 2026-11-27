import { describe, it, expect } from "vitest";
import { render, screen } from "@/test/utils";
import { ParameterCards } from "./ParameterCards";

describe("ParameterCards", () => {
  it("renders a string value as-is", async () => {
    await render(
      <ParameterCards parameters={[{ key: "log_level", value: "debug" }]} />,
    );
    expect(screen.getByText("debug")).toBeInTheDocument();
  });

  it("renders a number value as-is with an integer type badge", async () => {
    await render(
      <ParameterCards parameters={[{ key: "replicas", value: 3 }]} />,
    );
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("integer")).toBeInTheDocument();
  });

  it("renders a boolean value as-is with a boolean type badge", async () => {
    await render(
      <ParameterCards parameters={[{ key: "enabled", value: true }]} />,
    );
    expect(screen.getByText("true")).toBeInTheDocument();
    expect(screen.getByText("boolean")).toBeInTheDocument();
  });

  it("renders a nested object value readably, not as [object Object]", async () => {
    await render(
      <ParameterCards
        parameters={[
          {
            key: "env_vars",
            value: [{ name: "LOG_LEVEL", value: "debug" }],
          },
        ]}
      />,
    );

    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
    expect(screen.getByText(/LOG_LEVEL/)).toBeInTheDocument();
  });

  it("labels an object value's type badge as object, not string", async () => {
    await render(
      <ParameterCards
        parameters={[
          {
            key: "scheduling",
            value: { cron: "0 0 * * *" },
          },
        ]}
      />,
    );

    expect(screen.getByText("object")).toBeInTheDocument();
  });
});
