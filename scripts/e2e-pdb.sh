#!/usr/bin/env bash
# Run an E2E test with --pdb from a shell that has no usable stdin (agent tool,
# background job). Rationale and the stop command: AGENTS.md "Debugging E2E Tests".
#
# Usage: scripts/e2e-pdb.sh <pytest-node-id> [extra pytest args...]
set -u -o pipefail

if [ "$#" -eq 0 ]; then
    echo "usage: ${0##*/} <pytest-node-id> [extra pytest args...]" >&2
    exit 2
fi

log=${E2E_PDB_LOG:-/tmp/pdb.log}
echo "e2e-pdb: pid=$$ log=$log (stop with: kill $$)" >&2

holder="" pytest_pid="" sig=""
dir=$(mktemp -d "${TMPDIR:-/tmp}/e2e-pdb.XXXXXX") || exit 1
trap '[ -n "$holder" ] && kill "$holder" 2>/dev/null; rm -rf "$dir"' EXIT
fifo=$dir/stdin
mkfifo "$fifo" || exit 1

# A signal ends pdb's input and interrupts a running test, so pytest runs its
# finalizers (the vcluster delete) before it exits.
stop() {
    sig=$1
    [ -n "$holder" ] && kill "$holder" 2>/dev/null
    [ -n "$pytest_pid" ] && kill -INT "$pytest_pid" 2>/dev/null
}
trap 'stop 130' INT
trap 'stop 143' TERM
trap 'stop 129' HUP

# Job control keeps SIGINT at its default in background jobs, so pytest can
# receive it, and makes `jobs -p` return the PID of `uv`.
set -m

# Holds the FIFO open; if this script is SIGKILLed it exits within a second,
# so pdb reads end of input and pytest still runs its teardown.
wrapper=$$
( while kill -0 "$wrapper" 2>/dev/null; do sleep 1; done; rm -rf "$dir" ) > "$fifo" &
holder=$!
disown "$holder"  # no "Terminated" job notice when it is killed

uv run pytest "$@" -v -s --pdb < "$fifo" 2>&1 | tee -i "$log" &
pipe=$!
pytest_pid=$(jobs -p %%)
[ -z "$sig" ] || stop "$sig"  # a signal that came before both jobs started

# A trapped signal interrupts `wait`, so wait again until the pipeline ends.
while :; do
    wait "$pipe"
    rc=$?
    kill -0 "$pipe" 2>/dev/null || break
done
exit "${sig:-$rc}"
