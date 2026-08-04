/**
 * Backup retention TTL validation (016-backup-retention-ttl).
 *
 * A client-side port of ``backend/styrmin_backend/services/backup/ttl.py``
 * so the environment Configuration tab can reject a malformed retention
 * value before spending a round-trip. The backend remains the authority:
 * every write still funnels through ``validate_backup_ttl`` on
 * ``BaseConfigSection``, which rejects anything this module lets slip with
 * an actionable typed error. This is a UX affordance, not a security
 * boundary — keep it in step with the Python rule, do not diverge from it.
 *
 * The rule: a strictly positive Go duration limited to ``h``/``m``/``s``
 * units and to the magnitude Go can represent. Compounds (``1h30m``) and
 * decimals (``1.5h``) are valid Go durations and accepted. There is no day
 * unit (Go has none, so ``30d`` would be rejected by Velero at apply
 * time), no bare integer (``720`` is ambiguous), and nothing above
 * {@link MAX_BACKUP_TTL_HOURS} (Go durations are int64 nanoseconds).
 */

/**
 * The built-in retention Velero applies when no scope sets a policy —
 * mirrors ``DEFAULT_BACKUP_TTL`` in the backend's ``ttl.py``. Shown in the
 * UI as the fallback an operator lands on after clearing a policy.
 */
export const DEFAULT_BACKUP_TTL = "720h";

/**
 * Upper bound in hours, mirroring ``MAX_BACKUP_TTL_HOURS``. Go durations
 * are int64 nanoseconds, so ``time.ParseDuration`` overflows above
 * 2562047.788…h; the backend rounds down to whole hours.
 */
export const MAX_BACKUP_TTL_HOURS = 2562047;

const MAX_BACKUP_TTL_SECONDS = MAX_BACKUP_TTL_HOURS * 3600;

/**
 * One or more ``<number><unit>`` components.
 *
 * ``[0-9]`` rather than ``\d`` to mirror the backend's deliberate choice
 * (Python's ``\d`` is Unicode-aware and would admit ``"٧٢٠h"``); spelling
 * the class out keeps the two patterns comparable character-for-character.
 *
 * Anchored ``^``…``$`` with **no** ``m`` flag: unlike Python's ``$``, a
 * JavaScript ``$`` without ``m`` matches only the very end of the input,
 * so ``"720h\n"`` is rejected here just as the backend's ``\A``/``\Z``
 * rejects it. Do not add the ``m`` flag — it would reopen that hole and
 * let an unparseable ``spec.ttl`` through to Velero.
 */
const BACKUP_TTL_PATTERN = /^(?:[0-9]+(?:\.[0-9]+)?(?:h|m|s))+$/;

/** Individual components, for the all-zero and overflow checks. */
const BACKUP_TTL_COMPONENT_PATTERN = /([0-9]+(?:\.[0-9]+)?)(h|m|s)/g;

const UNIT_SECONDS: Record<string, number> = { h: 3600, m: 60, s: 1 };

/**
 * Rejection message for a value that is not a positive h/m/s Go duration.
 * Phrased for the field's UI label; keeps the backend's ``"720h"`` hint.
 */
export const INVALID_BACKUP_TTL_MESSAGE =
  'Retention must be a positive Go duration using h/m/s units, e.g. "720h".';

/** Rejection message for a value above the Go int64-nanosecond ceiling. */
export const BACKUP_TTL_TOO_LARGE_MESSAGE =
  `Retention must not exceed ${MAX_BACKUP_TTL_HOURS}h — Go durations are ` +
  'int64 nanoseconds, so a larger value cannot be parsed (e.g. "720h").';

/**
 * Validate a candidate retention duration.
 *
 * Enforces the three backend rules in the same order: the syntax pattern,
 * at least one non-zero component (``0h`` / ``0h0m0s`` match the syntax
 * but express no retention, which Velero would read as "keep forever"),
 * and the magnitude ceiling.
 *
 * The value is validated **verbatim** — no trimming, so ``" 720h"`` is
 * rejected exactly as the backend rejects it. An empty string is likewise
 * invalid here; "no policy" is not a value, it is the absence of one, and
 * callers express it by submitting ``null`` (see ``BackupRetentionForm``,
 * which treats a blank input as "clear the policy" before ever reaching
 * this function).
 *
 * @param value - Candidate retention duration, e.g. ``"720h"``.
 * @returns ``null`` when the value is valid, otherwise the reason to show.
 */
export function validateBackupTtl(value: string): string | null {
  if (typeof value !== "string" || !BACKUP_TTL_PATTERN.test(value)) {
    return INVALID_BACKUP_TTL_MESSAGE;
  }

  // ``matchAll`` on a fresh iterator each call — the /g regex is
  // module-level, so relying on ``exec`` would carry ``lastIndex`` between
  // calls.
  const components = [...value.matchAll(BACKUP_TTL_COMPONENT_PATTERN)];
  let totalSeconds = 0;
  let sawNonZero = false;
  for (const [, amount, unit] of components) {
    const parsed = Number(amount);
    if (parsed > 0) sawNonZero = true;
    totalSeconds += parsed * UNIT_SECONDS[unit];
  }

  if (!sawNonZero) {
    return INVALID_BACKUP_TTL_MESSAGE;
  }
  if (totalSeconds > MAX_BACKUP_TTL_SECONDS) {
    return BACKUP_TTL_TOO_LARGE_MESSAGE;
  }
  return null;
}
