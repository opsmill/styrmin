#!/usr/bin/env bash
# Run an E2E test with --pdb from a shell that has no usable stdin (agent tool,
# background job). Rationale and the stop command: AGENTS.md "Debugging E2E Tests".
#
# Usage: scripts/e2e-pdb.sh <test path or node id> [more pytest args...]
set -u -o pipefail

# Without a test path pytest collects from the current directory, so refuse to start.
has_path=""
for arg in "$@"; do
    [ -e "${arg%%::*}" ] && has_path=1 && break
done
if [ -z "$has_path" ]; then
    echo "usage: ${0##*/} <test path or node id> [more pytest args...]" >&2
    exit 2
fi

if [ -t 0 ]; then stop_hint="Ctrl-C, then q at the pdb prompt"; else stop_hint="kill $$"; fi

# A log per run, so concurrent runs on one host never share one. BSD mktemp
# needs the X's at the end of the template.
log=${E2E_PDB_LOG:-}
[ -n "$log" ] || log=$(mktemp "${TMPDIR:-/tmp}/e2e-pdb-log.XXXXXX") || exit 2
start="e2e-pdb: pid=$$ log=$log (stop with: $stop_hint)"
if ! printf '%s\n' "$start" > "$log"; then
    echo "e2e-pdb: cannot write the log file $log; pytest was not started" >&2
    exit 2
fi
echo "$start" >&2

# At a terminal a person types pdb commands and Ctrl-C reaches pytest directly.
if [ -t 0 ]; then
    uv run pytest "$@" -v -s --pdb 2>&1 | tee -a -i "$log"
    rc=${PIPESTATUS[0]}
    echo "e2e-pdb: exit=$rc log=$log" >&2
    exit "$rc"
fi

holder="" pytest_pid="" sig=""
dir=$(mktemp -d "${TMPDIR:-/tmp}/e2e-pdb.XXXXXX") || exit 1
trap '[ -n "$holder" ] && kill "$holder" 2>/dev/null; rm -rf "$dir"' EXIT
fifo=$dir/stdin
mkfifo "$fifo" || exit 1

# A signal ends pdb's input and interrupts a running test, so pytest runs its
# finalizers (the vcluster delete) before it exits. At the pdb prompt end of
# input is enough, and a SIGINT there can go off later, during teardown.
stop() {
    sig=$1
    [ -n "$holder" ] && kill "$holder" 2>/dev/null
    if [ -n "$pytest_pid" ] && [ "$(tail -c 6 "$log")" != "(Pdb) " ]; then
        kill -INT "$pytest_pid" 2>/dev/null
    fi
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

uv run pytest "$@" -v -s --pdb < "$fifo" 2>&1 | tee -a -i "$log" &
pipe=$!
pytest_pid=$(jobs -p %%)
[ -z "$sig" ] || stop "$sig"  # a signal that came before both jobs started

# A trapped signal interrupts `wait`, so wait again until the pipeline ends.
while :; do
    wait "$pipe"
    rc=$?
    kill -0 "$pipe" 2>/dev/null || break
done
rc=${sig:-$rc}
echo "e2e-pdb: exit=$rc log=$log" >&2
exit "$rc"
