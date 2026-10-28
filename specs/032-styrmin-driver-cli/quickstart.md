# Quickstart: validate `styrmin-driver`

This guide lists the commands that show the feature works. The command interface is in [contracts/cli.md](contracts/cli.md), and the entities are in [data-model.md](data-model.md).

## Prerequisites

- A clone of the repository, with `uv sync` run at its root. No Styrmin server, database or cluster runs.
- For the image scenario: Docker, and either a local build (`docker compose build`) or a pull of `registry.opsmill.io/opsmill/styrmin:<tag>`, which needs no credentials.
- For the E2E scenario: `vcluster` and `docker` on the PATH, as for every E2E test ([`AGENTS.md`](../../AGENTS.md), "Debugging E2E Tests").

## 1. The eight example drivers pass (SC-001)

```bash
for d in driver/examples/*/; do uv run styrmin-driver check "$d" || echo "FAILED: $d"; done
```

Expected: one summary line per driver, with no errors, and no `FAILED` line. Warnings are expected:

- `generic-app` and `infrahub-mcp` each print one placeholder warning for a parameter ([research R-006](research.md#r-006-placeholder-values-for-parameters-without-a-default));
- every driver except `semaphore` prints one warning for the application version, because only `semaphore` sets `default_version` ([R-007](research.md#r-007-how-the-example-context-is-built)).

## 2. Every error in one run, with its file and line (user story 1)

```bash
cp -r driver/examples/simple-app "$TMPDIR/broken"
# Line 12 of values.j2.yml: use an undefined variable.
# driver.styrmin.yml: point the upgrade action to a function that actions.py does not define.
uv run styrmin-driver check "$TMPDIR/broken"; echo "exit $?"
```

Expected: one `values.j2.yml:12: error: undefined variable ...` line, one `driver.styrmin.yml:<line>: error: Missing entrypoint for action upgrade: ...` line, the summary `2 errors`, and `exit 1`. After both fixes: `exit 0`.

## 3. Render with a context file, and view the example context (user story 2)

```bash
uv run styrmin-driver context driver/examples/generic-app
printf 'parameters:\n  image_tag: "1.2.3"\n' > "$TMPDIR/ctx.yml"
uv run styrmin-driver render driver/examples/generic-app > "$TMPDIR/default.yml"
uv run styrmin-driver render driver/examples/generic-app --context "$TMPDIR/ctx.yml" > "$TMPDIR/tagged.yml"
diff "$TMPDIR/default.yml" "$TMPDIR/tagged.yml"
```

Expected:

- `context` prints the parameter defaults, components and services of `generic-app`, and a warning for `image_repository` on standard error.
- Both renders exit with 0, and each output file holds only YAML values.
- `diff` shows only the lines that come from `image_tag`.

Then the rejection of a mistyped key (FR-004):

```bash
printf 'parameterz:\n  image_tag: "1.2.3"\n' > "$TMPDIR/typo.yml"
uv run styrmin-driver render driver/examples/generic-app --context "$TMPDIR/typo.yml"; echo "exit $?"
```

Expected: an error on standard error that names `parameterz`, nothing on standard output, and `exit 2`.

## 4. Compare values, not text (user story 3)

```bash
uv run styrmin-driver diff driver/examples/generic-app --base "$TMPDIR/default.yml"; echo "exit $?"
uv run styrmin-driver diff driver/examples/generic-app --context "$TMPDIR/ctx.yml" --base "$TMPDIR/default.yml"; echo "exit $?"
```

Expected: `exit 0` with no output for the first command; a unified diff of the image tag and `exit 1` for the second. Reorder the keys of `default.yml` by hand and run the first command again: `exit 0`.

## 5. Exit code 2 when the command cannot run (FR-012)

```bash
uv run styrmin-driver check /does/not/exist; echo "exit $?"
uv run styrmin-driver check driver/examples/simple-app --bogus; echo "exit $?"
uv run styrmin-driver diff driver/examples/simple-app --base /does/not/exist.yml; echo "exit $?"
```

Expected: `exit 2` three times.

## 6. From the Styrmin image (FR-014)

```bash
docker run --rm registry.opsmill.io/opsmill/styrmin:<tag> styrmin-driver check /styrmin/drivers/simple-app; echo "exit $?"
docker run --rm -v "$PWD/my-driver:/work/my-driver:ro" registry.opsmill.io/opsmill/styrmin:<tag> styrmin-driver render /work/my-driver
```

Expected: `exit 0` for the first command, and the rendered values for the second. `<tag>` is a release that contains this feature, or `latest` after a local `docker compose build`.

## 7. Time to a first render (SC-002)

```bash
time (uv run styrmin-driver check driver/examples/simple-app && uv run styrmin-driver render driver/examples/simple-app > /dev/null)
```

Expected: well under one minute on a clone where `uv sync` has run.

## 8. Tests

```bash
uv run pytest -v python_sdk/tests/driver            # the tool, with network access turned off (FR-013)
uv run pytest -v backend/tests/unit/services/driver # the load and render still behave as before (FR-015, FR-016)
uv run invoke format lint
sleep infinity | uv run pytest "backend/tests/e2e/test_deploy_app.py::test_styrmin_driver_matches_helm_release" -v -s --pdb 2>&1 | tee "$TMPDIR/e2e.log"
```

Expected: all pass. The E2E node runs as `[api-chromium]` only, and its pass is recorded with the evidence that constitution section V requires (node ID, command, timestamp, cluster identifier and the `PASSED` line). The node name is the plan's choice ([research R-013](research.md#r-013-e2e-test-on-the-session-deployment-of-simple-app)).
