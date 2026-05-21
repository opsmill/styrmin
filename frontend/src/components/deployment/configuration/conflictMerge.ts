/**
 * Conflict-merge equality helper, scoped to the concurrent-edit reload path
 * in {@link ConfigDiffDialog}.
 *
 * Why it exists: TanStack Form's `<form.Field mode="array">` normalises an
 * unset `defaultValues.envVars = undefined` into `state.values.envVars = []`
 * on first render. The reload-and-merge logic compares the form's current
 * value against a frozen drawer-open baseline to decide which top-level
 * fields the operator actually edited; without this tolerance, the form's
 * `[]` would diverge from a baseline `undefined`, the field would be tagged
 * "edited", and the refreshed-baseline value would be silently dropped.
 *
 * Scope is intentionally narrow — do NOT reuse this for general value
 * comparison. An operator clearing a list (envVars: ["FOO=1"] → []) is a
 * real edit that semantically differs from "never touched"; that distinction
 * only collapses inside the merge because the frozen baseline disambiguates.
 */

function asFormArrayEmpty(v: unknown): unknown {
  if (v === undefined || v === null) return null;
  if (Array.isArray(v) && v.length === 0) return null;
  if (
    typeof v === "object" &&
    v !== null &&
    !Array.isArray(v) &&
    Object.keys(v as Record<string, unknown>).length === 0
  ) {
    return null;
  }
  return v;
}

/**
 * `true` when `a` and `b` represent the same value under the
 * form-array-empty tolerance described in the module docstring.
 */
export function formArrayEmptyEqual(a: unknown, b: unknown): boolean {
  return (
    JSON.stringify(asFormArrayEmpty(a)) === JSON.stringify(asFormArrayEmpty(b))
  );
}
