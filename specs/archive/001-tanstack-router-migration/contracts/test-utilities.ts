/**
 * Test Utilities Contract — TanStack Router Migration
 *
 * This file defines the expected API surface for test utilities
 * after the migration. It is NOT production code.
 */

import type { ReactElement } from "react";
import type { RenderOptions, RenderResult } from "@testing-library/react";

// === Custom Render Function ===

/**
 * The custom render function must:
 * 1. Create a TanStack Router instance with memory history
 * 2. Wrap the component under test in RouterProvider
 * 3. Support an optional initialLocation parameter
 * 4. Return the standard RTL render result
 *
 * Signature:
 */
interface CustomRenderOptions extends Omit<RenderOptions, "wrapper"> {
  /** Initial URL for the memory history. Defaults to "/" */
  initialLocation?: string;
}

type CustomRender = (
  ui: ReactElement,
  options?: CustomRenderOptions,
) => RenderResult;

// === Re-exports ===

/**
 * The test utils module must continue to re-export:
 * - render (custom, with router wrapper)
 * - screen
 * - within
 * - waitFor
 * - userEvent
 */

export type { CustomRender, CustomRenderOptions };
