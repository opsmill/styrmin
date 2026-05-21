/**
 * Loose alias for the TanStack-Form "extended" form API surface that the
 * section components consume.
 *
 * The drawer owns the typed `useForm<UpdateDeploymentInput>(...)` instance.
 * Threading its generic signature (10+ type parameters, every validator
 * adapter type) into every section file produces no useful narrowing — the
 * field paths each section binds to (e.g. `scheduling.resources.requests.cpu`,
 * `scheduling.tolerations.0.effect`) traverse the input schema dynamically,
 * and the form's per-path field-value inference is not exposed for arbitrary
 * dotted strings. We accept the form prop as `any` here and rely on
 * surrounding Zod schemas + on-submit validation for runtime safety.
 *
 * The structural escape hatch is intentional and scoped to this directory.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ReactFormLike = any;
