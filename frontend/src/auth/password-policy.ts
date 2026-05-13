/**
 * Password-policy guidance, mirrored from
 * `backend/styrmin_backend/services/auth/password.py` (`MIN_PASSWORD_LENGTH`
 * and `MAX_PASSWORD_LENGTH`).
 *
 * The backend is the source of truth — these strings exist only so we can
 * render hints next to the password field. We deliberately do NOT validate
 * client-side; that lets us avoid drift when the backend policy changes and
 * keeps a single rejection path in the server.
 */
export const PASSWORD_MIN_LENGTH = 5;
export const PASSWORD_MAX_LENGTH = 256;

export const PASSWORD_REQUIREMENTS: string[] = [
  `At least ${PASSWORD_MIN_LENGTH} characters`,
  `At most ${PASSWORD_MAX_LENGTH} characters`,
];

/**
 * Single-line summary suitable for inline placement under a password input
 * (where a bullet list would feel too heavy).
 */
export const PASSWORD_REQUIREMENTS_SUMMARY = `Between ${PASSWORD_MIN_LENGTH} and ${PASSWORD_MAX_LENGTH} characters.`;
