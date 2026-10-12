/**
 * Extract a human-readable message from a TanStack Form field error, which may
 * be a plain string or a standard-schema issue object (`{ message }`). Avoids
 * rendering "[object Object]".
 */
export function fieldError(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return "Invalid value";
}
