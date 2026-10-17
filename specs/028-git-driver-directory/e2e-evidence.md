# E2E Evidence: Load an Application Driver from a Driver Directory of a Git Repository

This file records the local E2E runs for spec 028 ([#517](https://github.com/opsmill/styrmin/issues/517)), with the details that Constitution §V asks for: the pytest node IDs, the exact command, the start and end times, the vcluster and its kubeconfig path, and the `PASSED` lines as pytest printed them. Each run has its own section; add later runs at the end of the file.

- Branch: `fac/check-driver-from-git-repo-works-0d15v`
- Every run gives pytest a standard input that stays open, so `--pdb` can stop at a failure, and stops only its own `sleep` afterwards (the pattern in each command).
- Colour codes are removed from the quoted pytest lines. With `-s`, other output can sit between a node ID and its `PASSED`; where it does, the node ID is given with the line.

## Early single-test run for T026 and T027 (API variant)

This run checks the fixture change of T024 and T026 and the assertions of T027 before the full shard runs. The full `shard_general` runs are T052 (API variant) and T053 (UI variant).

- Commit tested: `6595abcb` ("test(drivers): load the session E2E driver from a driver directory (#517)").
- Command, from the repository root:

  ```bash
  export STYRMIN_IMAGE_VER=e2e028-1792262388
  docker compose build server
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e/test_driver_version_reselection.py -m "ci and shard_general" -k api-chromium -v -s --pdb <&3 > e2e-attempt1.log 2>&1
  exec 3<&-; kill "$spid"
  ```

- Start: 2026-10-17T18:40:00Z. End: 2026-10-17T18:43:40Z.
- vcluster: `pytest-fffb29b8-ba8c-4d5e-a83d-4346251da1e9`.
- Kubeconfig: `/tmp/pytest-of-root/pytest-1948/vcluster0/kubeconfig`.
- Collected: `collected 4 items / 2 deselected / 2 selected`.
- In this session, `styrmin_resources` loaded `simple-app` from the driver directory `drivers/simple-app` of `git://git-server.default.svc.cluster.local/driver-collection.git`, and `deployed_simple_app` deployed that driver version and ran its setup actions. The test then checked that the driver version stores `sourcePath == "drivers/simple-app"` and that its Prefect action deployments, tagged `fingerprint/<commit>` and `directory/drivers/simple-app`, have the pull steps `git_clone` then `set_working_directory` into `.../drivers/simple-app`.
- `test_drivers_list_caps_long_histories` is `ui_only`, so the API variant skips it.

Result lines:

```text
backend/tests/e2e/test_driver_version_reselection.py::test_driver_version_reselection[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_driver_version_reselection.py::test_drivers_list_caps_long_histories[api-chromium] SKIPPED
====== 1 passed, 1 skipped, 2 deselected, 1 warning in 218.29s (0:03:38) =======
```
