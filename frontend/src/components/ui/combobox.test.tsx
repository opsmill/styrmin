/**
 * Combobox primitive tests.
 *
 * The wrapper's reason to exist is the search field inside the popup, so the
 * cases below cover the contract consumers depend on: the trigger reads like a
 * Select's, typing narrows the list through Base UI's own filtering, a miss
 * renders the empty slot, and picking a row reports the item's string value.
 */
import { describe, it, expect, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { render, screen, userEvent } from "@/test/utils";

import {
  Combobox,
  ComboboxTrigger,
  ComboboxContent,
  ComboboxSearch,
  ComboboxList,
  ComboboxItem,
  ComboboxEmpty,
  ComboboxFooter,
} from "./combobox";

const OPTIONS = [
  { value: "v3", label: "3.2.1" },
  { value: "v2", label: "3.1.4" },
  { value: "v1", label: "2.0.9" },
];

function Picker({
  onValueChange = vi.fn(),
}: {
  onValueChange?: (v: string) => void;
}) {
  return (
    <Combobox items={OPTIONS} value="v3" onValueChange={onValueChange}>
      <ComboboxTrigger aria-label="Switch version">3.2.1</ComboboxTrigger>
      <ComboboxContent>
        <ComboboxSearch aria-label="Search versions" placeholder="Search…" />
        <ComboboxList>
          {(option: (typeof OPTIONS)[number]) => (
            <ComboboxItem key={option.value} value={option.value}>
              {option.label}
            </ComboboxItem>
          )}
        </ComboboxList>
        <ComboboxEmpty>No version matches</ComboboxEmpty>
        <ComboboxFooter>Newest first</ComboboxFooter>
      </ComboboxContent>
    </Combobox>
  );
}

describe("Combobox", () => {
  it("opens from the trigger and lists every option", async () => {
    await render(<Picker />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("combobox", { name: "Switch version" }));

    expect(await screen.findByText("3.1.4")).toBeInTheDocument();
    expect(screen.getByText("2.0.9")).toBeInTheDocument();
    expect(screen.getByText("Newest first")).toBeInTheDocument();
  });

  it("narrows the list to what was typed", async () => {
    await render(<Picker />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("combobox", { name: "Switch version" }));
    await user.type(await screen.findByLabelText("Search versions"), "3.1");

    await waitFor(() => {
      expect(screen.queryByText("2.0.9")).not.toBeInTheDocument();
    });
    expect(screen.getByText("3.1.4")).toBeInTheDocument();
  });

  it("renders the empty slot when nothing matches", async () => {
    await render(<Picker />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("combobox", { name: "Switch version" }));
    await user.type(await screen.findByLabelText("Search versions"), "9.9.9");

    expect(await screen.findByText("No version matches")).toBeInTheDocument();
  });

  it("reports the picked option's string value", async () => {
    const onValueChange = vi.fn();
    await render(<Picker onValueChange={onValueChange} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("combobox", { name: "Switch version" }));
    await user.click(await screen.findByText("3.1.4"));

    await waitFor(() => expect(onValueChange).toHaveBeenCalledWith("v2"));
  });
});
