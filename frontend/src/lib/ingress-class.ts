import type { ServiceConfigInput } from "@/generated/graphql";

/**
 * Validation of the ingress class of a service ingress override (#598).
 *
 * Mirrors `validate_service_ingress_class` in
 * `backend/styrmin_backend/context/models/config.py`: the class is written to
 * `spec.ingressClassName` and to an annotation of the Ingress, so it must be a
 * Kubernetes object name (a DNS-1123 subdomain): dot-separated labels of
 * lowercase letters, digits or hyphens, each starting and ending with a letter
 * or a digit, at most 253 characters in total. Keep the two in step: the
 * backend rejects what this lets through. An empty class is no override, so it
 * is not an error here; the backend rejects an empty string and a client
 * clears an override by omitting the field.
 */
export const INGRESS_CLASS_MAX_LENGTH = 253;

// `$` without the `m` flag matches only at the end of the string in JavaScript,
// so a trailing newline is rejected.
const INGRESS_CLASS =
  /^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$/;

const MESSAGE =
  "The ingress class must be a Kubernetes object name: lowercase letters, " +
  "digits, hyphens and dots, starting and ending with a letter or a digit, " +
  `at most ${INGRESS_CLASS_MAX_LENGTH} characters.`;

/** The message for an invalid ingress class, or `null` when it is valid or empty. */
export function ingressClassError(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  if (value.length > INGRESS_CLASS_MAX_LENGTH) return MESSAGE;
  return INGRESS_CLASS.test(value) ? null : MESSAGE;
}

/** The service names whose ingress class is invalid, in row order. */
export function servicesWithInvalidClass(
  rows: readonly ServiceConfigInput[] | null | undefined,
): string[] {
  return (rows ?? [])
    .filter((row) => row && ingressClassError(row.ingressClass) !== null)
    .map((row) => row.name);
}
