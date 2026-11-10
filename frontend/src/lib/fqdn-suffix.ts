import type { ServiceConfigInput } from "@/generated/graphql";

/**
 * Validation of the FQDN suffix of a service ingress override (#598).
 *
 * Mirrors `validate_service_fqdn_suffix` in
 * `backend/styrmin_backend/context/models/config.py`: the suffix is a DNS name
 * of dot-separated labels, each of 1 to 63 lowercase letters, digits or hyphens
 * that starts and ends with a letter or a digit, at most 253 characters in
 * total, with no leading, trailing or doubled dot. Keep the two in step: the
 * backend rejects what this lets through. (The backend matches each label with
 * `re.fullmatch`, so, like this rule, it rejects a suffix that ends in a newline.)
 * An empty suffix is no override, so it is not an error here; the backend rejects an
 * empty string and a client clears an override by omitting the field.
 */
export const FQDN_SUFFIX_MAX_LENGTH = 253;

const LABEL = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;

const MESSAGE =
  "The FQDN suffix must be a DNS name: dot-separated labels of 1 to 63 " +
  "lowercase letters, digits or hyphens, each starting and ending with a " +
  `letter or a digit, at most ${FQDN_SUFFIX_MAX_LENGTH} characters in total.`;

/** The message for an invalid suffix, or `null` when it is valid or empty. */
export function fqdnSuffixError(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  if (value.length > FQDN_SUFFIX_MAX_LENGTH) return MESSAGE;
  return value.split(".").every((label) => LABEL.test(label)) ? null : MESSAGE;
}

/** The service names whose FQDN suffix is invalid, in row order. */
export function servicesWithInvalidSuffix(
  rows: readonly ServiceConfigInput[] | null | undefined,
): string[] {
  return (rows ?? [])
    .filter((row) => row && fqdnSuffixError(row.fqdnSuffix) !== null)
    .map((row) => row.name);
}
