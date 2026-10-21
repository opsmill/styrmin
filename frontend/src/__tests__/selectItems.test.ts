/**
 * Every select whose trigger shows the selected item with `<SelectValue>`
 * passes `items`. Without it, Base UI shows the raw value of the selected
 * item in the trigger, for example an id instead of a name. A select whose
 * items show their own value, such as `<SelectItem value={op}>{op}</SelectItem>`,
 * needs no `items`.
 */
import { describe, it, expect } from "vitest";

const SOURCES = import.meta.glob<string>(
  ["../**/*.tsx", "!../**/*.test.tsx", "!../__tests__/**"],
  { query: "?raw", import: "default", eager: true },
);

const SELECT_START = /<Select(?=[\s>])/g;
const ITEM =
  /<SelectItem\b[^>]*?\bvalue=\{([^}]+)\}[^>]*>\s*\{([^}]+)\}\s*<\/SelectItem>/g;

/** Return the line of each select in `source` that shows a raw value in its trigger. */
function selectsShowingRawValues(source: string): number[] {
  const lines: number[] = [];
  for (const match of source.matchAll(SELECT_START)) {
    const start = match.index;
    const end = source.indexOf("</Select>", start);
    const block = source.slice(start, end === -1 ? undefined : end);
    if (!block.includes("<SelectValue")) continue;
    const trigger = block.indexOf("<SelectTrigger");
    const root = trigger === -1 ? block : block.slice(0, trigger);
    if (root.includes("items=")) continue;
    const items = [...block.matchAll(ITEM)];
    const itemCount = block.match(/<SelectItem\b/g)?.length ?? 0;
    const showsOwnValue =
      items.length === itemCount &&
      items.every(([, value, label]) => value!.trim() === label!.trim());
    if (!showsOwnValue) {
      lines.push(source.slice(0, start).split("\n").length);
    }
  }
  return lines;
}

describe("selectsShowingRawValues", () => {
  it("finds a select whose items show a label that is not their value", () => {
    const source = [
      "<Select value={id}>",
      "  <SelectTrigger><SelectValue /></SelectTrigger>",
      "  <SelectContent>",
      "    {rows.map((row) => (",
      "      <SelectItem key={row.id} value={row.id}>",
      "        {row.name}",
      "      </SelectItem>",
      "    ))}",
      "  </SelectContent>",
      "</Select>",
    ].join("\n");

    expect(selectsShowingRawValues(source)).toEqual([1]);
  });

  it("accepts a select with items, or whose items show their own value", () => {
    const withItems = [
      "<Select items={options} value={id}>",
      "  <SelectTrigger><SelectValue /></SelectTrigger>",
      '  <SelectContent><SelectItem value="any">Any</SelectItem></SelectContent>',
      "</Select>",
    ].join("\n");
    const ownValue = [
      "<Select value={op}>",
      "  <SelectTrigger><SelectValue /></SelectTrigger>",
      "  <SelectContent>",
      "    {OPS.map((op) => (",
      "      <SelectItem key={op} value={op}>",
      "        {op}",
      "      </SelectItem>",
      "    ))}",
      "  </SelectContent>",
      "</Select>",
    ].join("\n");

    expect(selectsShowingRawValues(withItems)).toEqual([]);
    expect(selectsShowingRawValues(ownValue)).toEqual([]);
  });
});

describe("selects of the application", () => {
  it("show the label of the selected item, not its raw value", () => {
    const found = Object.entries(SOURCES).flatMap(([path, source]) =>
      selectsShowingRawValues(source).map((line) => `${path}:${line}`),
    );

    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    expect(found).toEqual([]);
  });
});
