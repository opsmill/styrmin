import { describe, it, expect } from "vitest";

import {
  BACKUP_TTL_TOO_LARGE_MESSAGE,
  DEFAULT_BACKUP_TTL,
  INVALID_BACKUP_TTL_MESSAGE,
  MAX_BACKUP_TTL_HOURS,
  validateBackupTtl,
} from "./backup-ttl";

/**
 * The accept/reject matrix mirrors the backend rule in
 * ``backend/styrmin_backend/services/backup/ttl.py`` (pinned there by
 * ``backend/tests/unit/context/test_base_config_section.py``) — the two
 * implementations must agree, or the UI either blocks a value the backend
 * would take or waves through one it will reject.
 */
describe("validateBackupTtl", () => {
  it.each([
    "720h",
    "2160h",
    "8760h",
    "1h",
    "90m",
    "3600s",
    "1h30m",
    "1h30m15s",
    "1.5h",
    "0.5h",
    "0h1s", // a zero component is fine as long as one is non-zero
    `${MAX_BACKUP_TTL_HOURS}h`, // exactly at the Go int64-nanosecond ceiling
  ])("accepts %o", (value) => {
    expect(validateBackupTtl(value)).toBeNull();
  });

  it.each([
    ["30d", "no day unit in Go durations"],
    ["720", "bare integer is ambiguous"],
    ["", "empty is the absence of a value, not a value"],
    ["0h", "expresses no retention"],
    ["0h0m0s", "all-zero compound expresses no retention"],
    ["0.0h", "zero decimal expresses no retention"],
    ["-24h", "negative"],
    ["24H", "Go durations are case-sensitive"],
    [" 720h", "leading whitespace"],
    ["720h ", "trailing whitespace"],
    ["720h\n", "trailing newline would reach Velero as an unparseable ttl"],
    ["7 20h", "internal whitespace"],
    ["h", "no amount"],
    ["720hh", "duplicated unit without an amount"],
    ["1.h", "malformed decimal"],
    [".5h", "leading-dot decimal is not a Go duration"],
    ["1w", "unsupported unit"],
    ["1ms", "sub-second units are not accepted"],
    ["٧٢٠h", "non-ASCII digits Go cannot parse"],
  ])("rejects %o (%s)", (value) => {
    expect(validateBackupTtl(value)).toBe(INVALID_BACKUP_TTL_MESSAGE);
  });

  it("rejects a duration above the Go int64-nanosecond ceiling", () => {
    expect(validateBackupTtl(`${MAX_BACKUP_TTL_HOURS + 1}h`)).toBe(
      BACKUP_TTL_TOO_LARGE_MESSAGE,
    );
    // One second past the rounded-down ceiling also overflows.
    expect(validateBackupTtl(`${MAX_BACKUP_TTL_HOURS}h1s`)).toBe(
      BACKUP_TTL_TOO_LARGE_MESSAGE,
    );
    expect(validateBackupTtl("8760000h")).toBe(BACKUP_TTL_TOO_LARGE_MESSAGE);
  });

  it("keeps the backend's 720h hint in the invalid message", () => {
    expect(INVALID_BACKUP_TTL_MESSAGE).toContain('"720h"');
    expect(BACKUP_TTL_TOO_LARGE_MESSAGE).toContain('"720h"');
  });

  it("is stateless across repeated calls (module-level /g regex)", () => {
    expect(validateBackupTtl("1h30m")).toBeNull();
    expect(validateBackupTtl("1h30m")).toBeNull();
    expect(validateBackupTtl("0h")).toBe(INVALID_BACKUP_TTL_MESSAGE);
    expect(validateBackupTtl("0h")).toBe(INVALID_BACKUP_TTL_MESSAGE);
  });

  it("pins the built-in default to the backend's literal", () => {
    expect(DEFAULT_BACKUP_TTL).toBe("720h");
    expect(validateBackupTtl(DEFAULT_BACKUP_TTL)).toBeNull();
  });
});
