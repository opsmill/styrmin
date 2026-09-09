#!/usr/bin/env bash
# Run an E2E test with --pdb from a shell that has no usable stdin.
#
# pdb needs a stdin that never reaches EOF. Without one, a failing test exits
# pytest immediately and the vcluster is torn down before anyone can inspect
# it. A FIFO held open by a backgrounded `sleep` supplies that.
#
# Do NOT go back to `sleep infinity | uv run pytest ...`. That holds stdin open
# too, but `sleep` never writes, so it never takes SIGPIPE when pytest exits
# and the shell waits on it forever: the command hangs once the run finishes,
# including when the test passes. A background job started that way never
# reports completion, and any consumer that buffers rather than streams
# (`tail`, a pager) discards the output when it is finally killed.
#
# Usage:
#   scripts/e2e-pdb.sh <pytest-node-id> [extra pytest args...]
#
# Examples:
#   scripts/e2e-pdb.sh backend/tests/e2e/test_backup_restore.py
#   scripts/e2e-pdb.sh "backend/tests/e2e/test_x.py::test_y[ui-chromium]" --tb=long
#
# Writes a combined log to $E2E_PDB_LOG (default /tmp/pdb.log) and exits with
# pytest's own status.
set -u

if [ "$#" -eq 0 ]; then
    echo "usage: ${0##*/} <pytest-node-id> [extra pytest args...]" >&2
    exit 2
fi

log=${E2E_PDB_LOG:-/tmp/pdb.log}

fifo=$(mktemp -u)
mkfifo "$fifo" || exit 1

# Armed before the holder starts, so an interrupted run still cleans up:
# Ctrl-C, a killed agent run, or a caller's `set -e` tripping all skip the
# tail of this script, orphaning the holder process and leaving the FIFO in
# /tmp.
holder=""
trap '[ -n "$holder" ] && kill "$holder" 2>/dev/null; rm -f "$fifo"' EXIT INT TERM

sleep infinity > "$fifo" &
holder=$!

uv run pytest "$@" -v -s --pdb < "$fifo" 2>&1 | tee "$log"
exit "${PIPESTATUS[0]}"
