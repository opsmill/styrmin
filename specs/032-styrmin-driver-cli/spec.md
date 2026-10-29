# Feature Specification: Check, Render and Compare an Application Driver on the Author's Machine with `styrmin-driver`

**Feature Branch**: `032-styrmin-driver-cli`

**Created**: 2026-10-28

**Status**: Draft

**Input**: Brief "Problem, proposed tool and open decisions" — [opsmill/styrmin#23 (comment)](https://github.com/opsmill/styrmin/issues/23#issuecomment-6466328637). Seed issue: [#23](https://github.com/opsmill/styrmin/issues/23). The brief's links point to `develop` at [`8f450f6`](https://github.com/opsmill/styrmin/commit/8f450f6978a36bc1f6ea86c09fb99a47bb4ad904), and this spec is written against the same commit.

## Context

A driver author finds most errors in an **application driver** only when a running Styrmin loads or deploys it:

- A load from a local directory (`styrminctl drivers load-local-version`) parses `driver.styrmin.yml`, checks it, and stops at the first error ([`loaders.py`](../../backend/styrmin_backend/services/driver/loaders.py#L169-L205)).
- The agent renders `values.j2.yml` with `SilentUndefined`, so an undefined variable that the template writes out renders as an empty string and nothing reports it. Some other uses give another value with no message, and others make the render fail with a message that gives no line ([`application.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py#L171-L177), [`render_value_template`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py#L224-L285)).
- The user documentation tells the author to load the driver and create a deployment to test it ([`creating-a-driver.md`, step 9](../../docs/docs/drivers/creating-a-driver.md#L653)).

The code that reads, checks and renders a driver is in the backend, and it imports the backend's dependencies. The renderer's module imports Prefect ([`application.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py#L1-L5)). The local driver provider imports dulwich, loguru and the server configuration ([`provider.py`](../../backend/styrmin_backend/services/driver/provider.py#L1-L11)). The glossary defines `styrminctl` as a thin client over the GraphQL API ([`CONTEXT.md`](../../CONTEXT.md#L24-L26)), and it depends only on the SDK, Cyclopts, Rich, pydantic-settings, PyYAML and httpx ([`cli/pyproject.toml`](../../cli/pyproject.toml#L7-L14)).

An offline check script, `check_driver.py`, exists in the `creating-styrmin-drivers` agent skill, outside this repository. According to the brief, it holds a copy of the loader rules of Styrmin 0.1.54, so it falls out of date with each release.

The driver format changed after issue #23 was written. A **driver directory** holds `driver.styrmin.yml`, `values.j2.yml` and `actions.py`, and actions are declared under `spec.actions` in `driver.styrmin.yml`. There is no `actions.yaml` ([`CONTEXT.md`, "Driver directory" and "Action"](../../CONTEXT.md#L113-L163)).

This feature adds a command-line tool, `styrmin-driver`, that is installed with the SDK and present in the Styrmin image. Its four commands check a driver directory, render `values.j2.yml`, print the **example context**, and compare rendered values with a saved file. It needs no Styrmin server, database, cluster or network access. The code that reads, checks and renders a driver directory moves to the SDK, and the server's driver load and the agent's render use that code, so the tool and Styrmin apply the same rules.

## Clarifications

### Session 2026-10-28 (decisions recorded in the brief)

- Q: Where does the driver code live, and which command runs it? → A: In the SDK, with a dedicated command, `styrmin-driver`, and not in `styrminctl`. Fatih proposed it on Slack on 2026-10-28, in a direct conversation with no link. The brief records it as decided. No backend module imports the SDK today (`grep -rn styrmin_sdk backend/styrmin_backend` finds nothing, and [`backend/pyproject.toml`](../../backend/pyproject.toml) does not list it), so the backend gains a dependency on the SDK. This needs an ADR.
- Q: Does the server's behavior change? → A: No. A load still stops at the first error, and the agent renders an undefined variable as it does today. Only `styrmin-driver` treats an undefined variable as an error. Making the server reject undefined variables would break drivers that load and work today, and is out of scope.
- Q: How do authors get the tool in the first version? → A: From a clone of the repository, with `uv run styrmin-driver`, and from the Styrmin image. The SDK is not published: no workflow in `.github/workflows/` publishes a Python package, and the SDK version is fixed at `0.1.0` ([`python_sdk/pyproject.toml`](../../python_sdk/pyproject.toml#L3)). Publishing the SDK to PyPI is for Damien and Fatih to decide when Styrmin is public.
- Q: Do driver actions change? → A: No. `actions.py` files import `styrmin_backend.actions` and Prefect ([infrahub `actions.py`](../../driver/examples/infrahub/actions.py#L1-L9)). `check` reads `actions.py` without running it, as the load does today ([`UserActionsValidator`](../../backend/styrmin_backend/services/driver/validators.py#L84-L104) parses it with `ast.parse`), so the check does not need the backend.

### Session 2026-10-28 (autonomous, from the code at `8f450f6`)

The brief leaves two questions open. The code, the documentation and the registry answer both, so later phases do not reopen them.

- Q: Do the values in a HelmRelease hold only the rendered template, or also keys that Styrmin adds (brief, open question 1; SC-004 depends on it)? → A: Only the rendered template. `ApplicationHelmReleaseBuilder.build` sets `spec.values` once, from `render_value_template`, and makes every other change (labels, replica counts, ingress class, scheduling, component container) with post-renderer patches ([`application.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py#L415-L500)). No other module in `backend/styrmin_backend` builds a `Values` block. This is read from the code. The E2E test of SC-004 observes it on a cluster.
- Q: Does pulling the Styrmin image from `registry.opsmill.io` need credentials (brief, open question 2; SC-002 depends on it)? → A: No. The documentation says the registry is public and needs no `imagePullSecret` ([`digitalocean.md`](../../docs/docs/installation/digitalocean.md#L68-L70), [lines 221 to 224](../../docs/docs/installation/digitalocean.md#L221-L224)). On 2026-10-28, an anonymous token request to `https://registry.opsmill.io/service/token` for `repository:opsmill/styrmin:pull` returned a token, and the manifest of `opsmill/styrmin:0.1.55` returned HTTP 200 with that token, with no credentials sent.
- Q: Which invalid drivers does FR-001 and SC-003 cover, given that the brief refers to "the loader's test fixtures"? → A: The fixtures directory `backend/tests/unit/services/driver/fixtures/local_driver_directory/` holds one invalid file, `invalid_driver.yaml`, and no test reads it. The invalid drivers that the backend's driver tests use are written inside the test functions under `backend/tests/unit/services/driver/`. The plan lists them, and SC-003 covers each one.
- Q: Why is this spec numbered 032? → A: The branch script proposed 031, because it does not read `specs/archive/`, which already holds `031-inplace-restore-target` and `031-recorded-feature-demos`. 032 is the next number not used in `specs/` or `specs/archive/`.

### Session 2026-10-28 (plan)

The plan found two cases where the brief's rules would make SC-001 fail, and changed two requirements. Both changes are for the user to confirm.

- Q: What does the example context hold for a parameter without a default? → A: A placeholder value of the parameter's kind, with a warning (FR-002). `generic-app` declares `image_repository` and `infrahub-mcp` declares `infrahub_address` without a default, and both templates use the parameter ([research R-006](research.md#r-006-placeholder-values-for-parameters-without-a-default)).
- Q: Is a field of the context model that has no value an undefined variable? → A: No (FR-007). `generic-app`, `infrahub` and `infrahub-enterprise` read `instance.config.fqdn_suffix`, `external_url_scheme` and `external_url_port`, which are absent from a context where they are not set. Under the brief's rule, `check` would fail on these three drivers. Only a name that is neither a field of the context model nor a key of the context is an error ([research R-004](research.md#r-004-a-field-of-the-context-model-without-a-value-is-not-an-error)).

### Session 2026-10-28 (implementation)

- Q: Do the eight example drivers pass `check` (SC-001)? → A: Seven do. `slurpit` does not: its `values.j2.yml` reads `services.slurpit.primary_fqdn` on lines 84 and 89, and its `driver.styrmin.yml` declares no `spec.services`, so on a deployment both values render empty unless another deployment of the environment declares a service named `slurpit`. Changing the driver changes what it deploys, so the decision is the user's. Until then, the test of SC-001 marks `slurpit` as an expected failure ([e2e-evidence.md](e2e-evidence.md), "Open decision").
- Q: Where are the tests of SC-003? → A: In `backend/tests/unit/services/driver/test_styrmin_driver_matches_load.py`, because they compare `check` with the real server load; the SDK's tests do not import the backend. 29 cases pass.
- Q: Does `context` exit with 1 when the template has an error? → A: No. `context` exits with 1 only when `driver.styrmin.yml` has errors, because an error of the template does not change the context ([contracts/cli.md](contracts/cli.md)).

### Session 2026-10-29 (reviews of the documentation of `check`)

- Q: Does `check` report every error of a driver in one run, as the brief's FR-009 asks? → A: No. It can report more errors in one run than a load, but some errors hide others: the checks call the load's code, which stops at some errors; a YAML syntax error or an error against the driver model in `driver.styrmin.yml` stops the render; and the render stops at its first error other than an undefined variable, and takes only some branches of the template. Three reviews of the documentation found more cases each time the documentation listed them one by one, so the reference page states the rule, gives examples, and tells the author to fix what `check` reports and run it again, until it reports no error. FR-001, FR-007 and FR-009 are narrowed to match. The author of the brief, Simon AURA--SCUSSEL, confirmed the narrowing on 2026-10-29, in a review session with no link.
- Q: Is an undefined variable passed to a filter or a test an error (FR-007)? → A: Yes. Two reviews found uses that the check render did not report: `items` gave an empty loop; `abs`, `round`, `tojson` and `range()` failed with a `TypeError` that did not name the variable; and tests such as `is none` were false. The check render now makes each filter and test record an undefined variable passed to it, apart from the `default()` filter and the `defined` and `undefined` tests.
- Q: After a use of an undefined variable that makes the server's render fail, such as `{{ x + 1 }}`, does the check render go on to find the next one? → A: No. Up to `3b406375`, the check render went on with a value of its own, and the reviews of each version found cases where it then took a branch that the server's render does not take, or hid an error that the server's render reports. The author of the brief, Simon AURA--SCUSSEL, chose on 2026-10-29, in a review session with no link, that the check render uses the server's undefined values, which also record their uses: it takes the server's branches and fails where the server's render fails, with its message and the line. The uses after a failure are checked in a later run.

## User Scenarios & Testing *(mandatory)*

The users are a person, or an AI agent such as one that runs the `creating-styrmin-drivers` skill, who writes a driver on their own machine with no Styrmin running. Later, CI in a repository of community drivers runs the same commands and reads the exit code. The brief orders the three journeys below by priority. Each can be tested on its own, and all three ship in one change.

### User Story 1 - Check a driver before loading it (Priority: P1)

The author runs `styrmin-driver check <dir>`. The tool runs the checks that a load from a local directory runs, then renders `values.j2.yml` with the example context, where an undefined variable is an error. It reports in one run the errors that it finds, more than a load reports, each with its file and, when it is known, its line, and exits with 0 when the driver passes and 1 when it has errors.

**Why this priority**: Today the author learns of each error from a load, one error per load, and never learns of an undefined variable. This is the brief's first priority.

**Independent Test**: Run `check` on a driver whose `values.j2.yml` uses an undefined variable on line 12 and whose `driver.styrmin.yml` declares an action that `actions.py` does not define. Both errors are listed and the exit code is 1. After both fixes, the exit code is 0.

**Acceptance Scenarios**:

1. **Given** a driver whose `values.j2.yml` uses `{{ parameters.admn_email }}` on line 12, and whose `driver.styrmin.yml` declares an action that `actions.py` does not define, **When** the author runs `styrmin-driver check` on the directory, **Then** the tool lists both errors, each with its file and line, and exits with 1.
2. **Given** the same driver after both fixes, **When** the author runs `check` again, **Then** the tool exits with 0.
3. **Given** a driver with an invalid field in `driver.styrmin.yml` and an action whose function is missing from `actions.py`, **When** the author runs `check`, **Then** both errors are reported in one run.
4. **Given** each of the eight example drivers in [`driver/examples`](../../driver/examples), **When** the author runs `check` on it, **Then** the tool exits with 0.
5. **Given** a driver whose `spec.info.icon` is not an absolute `https` URL, **When** the author runs `check`, **Then** the tool prints the load warning and exits with 0.
6. **Given** a directory without `driver.styrmin.yml`, **When** the author runs `check`, **Then** the tool reports that the file is missing and exits with 1.
7. **Given** a path that does not exist, **When** the author runs `check`, **Then** the tool exits with 2.

---

### User Story 2 - View the rendered Helm values and the context a template can use (Priority: P2)

The author runs `styrmin-driver render <dir>`, optionally with `--context <file>`. The tool writes the Helm values as YAML to standard output and nothing else, so the author can redirect the output to a file. Errors go to standard error. To learn which values a template can use, and to write a context file, the author runs `styrmin-driver context <dir>`, which prints the full example context.

**Why this priority**: Without it, the author can view the rendered values only in the HelmRelease of a real deployment. This is the brief's second priority.

**Independent Test**: Run `render` on `simple-app` with a context file that sets one parameter. The output is valid YAML, and it differs from the output without the context file only in the values that come from that parameter.

**Acceptance Scenarios**:

1. **Given** a driver directory and a context file that sets one parameter, **When** the author runs `styrmin-driver render <dir> --context <file>`, **Then** the tool writes the Helm values as YAML to standard output, and only the values that come from that parameter differ from a render without the file.
2. **Given** the same command with standard output redirected to a file, **When** it succeeds, **Then** the file holds only the Helm values, with no messages, and the exit code is 0.
3. **Given** a context file with a mistyped key, **When** the author runs `render`, **Then** the tool names the key on standard error and exits with 2.
4. **Given** a template with an undefined variable, **When** the author runs `render`, **Then** the tool writes the error to standard error, writes nothing to standard output, and exits with 1.
5. **Given** `simple-app`, **When** the author runs `styrmin-driver context driver/examples/simple-app`, **Then** the output holds the parameter defaults and the services that its `driver.styrmin.yml` declares, and the output validates against the context model.
6. **Given** a running deployment of `simple-app`, **When** `render` runs with the context of that deployment, **Then** the output has the same values as the HelmRelease of that deployment.

---

### User Story 3 - Compare the rendered values with a saved file (Priority: P3)

The author changes a driver template and wants to view what the change does to the Helm values. They run `styrmin-driver diff <dir> --base <file>`, optionally with `--context <file>`, where the base file holds values rendered from the previous version of the driver. The tool compares values, not text, shows the values that changed, and exits with 1 when values differ and 0 when nothing changed.

**Why this priority**: It lets an author confirm that a change to a template changes only the values they meant to change. This is the brief's third priority.

**Independent Test**: Save the output of `render`, change one value in the template, and run `diff` with the saved file as the base. The tool shows the changed value and exits with 1. Revert the change: the tool exits with 0.

**Acceptance Scenarios**:

1. **Given** a driver whose template changed, and a values file rendered from the previous version of the driver, **When** the author runs `styrmin-driver diff <dir> --context <file> --base <file>`, **Then** the tool shows the values that changed and exits with 1.
2. **Given** a base file with the same values, **When** the author runs `diff`, **Then** the tool exits with 0.
3. **Given** a base file with the same values in another key order, indentation or quoting, **When** the author runs `diff`, **Then** the tool exits with 0.
4. **Given** a base file where a value is `"8080"` and the render gives `8080`, **When** the author runs `diff`, **Then** the tool reports the difference and exits with 1, because Helm receives a different value.
5. **Given** a base file that does not exist or is not valid YAML, **When** the author runs `diff`, **Then** the tool exits with 2.

---

### Edge Cases

- `values.j2.yml` has a syntax error. Jinja stops parsing at the first one, so `check` reports that one error, with the other errors it found in `driver.styrmin.yml` and `actions.py`, and does not render the template (FR-009).
- `driver.styrmin.yml` is not valid YAML or does not match the driver model. The tool cannot build the example context from it, so `check` reports the errors in the file and does not render the template (FR-009). An error of a check across fields, or a missing action function, does not stop the render.
- A template tests `{% if parameters.helth_path %}` where the parameter is not declared. This is an error, because the test would otherwise be false with no message. `{% if parameters.helth_path is defined %}` and `{{ parameters.helth_path | default('/') }}` are not errors (FR-007).
- The real context leaves out a key when its value is empty. For example, `instance.config.fqdn_suffix` is absent when no FQDN suffix is set, because the renderer dumps the context with `exclude_none=True` ([`render_value_template`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py#L224-L285)). `generic-app`, `infrahub` and `infrahub-enterprise` read such keys in `values.j2.yml` (`instance.config.fqdn_suffix`, `instance.config.external_url_scheme`, `instance.config.external_url_port`). Such a key is a field of the context model, so it is not an error, and it renders as on the agent (FR-007).
- A context file sets a list. The list replaces the list of the example context. It is not merged item by item (FR-003).
- A context file is not valid YAML, or does not hold a mapping at its top level. The tool exits with 2 (FR-012).
- `actions.py` is not valid Python. `check` reports the syntax error and does not report missing functions, because it cannot read them. Today the load raises the error of `ast.parse` ([`validators.py`](../../backend/styrmin_backend/services/driver/validators.py#L88-L89)). Not known: whether today's message names the line. The plan checks it.
- A driver declares no action and has no `actions.py`. `check` reports no action error, as the load does: the load reads `actions.py` only when `spec.actions` is not empty ([`loaders.py`](../../backend/styrmin_backend/services/driver/loaders.py#L84-L94)).
- A driver has only load warnings. The tool prints them and exits with 0 (FR-010).
- An author runs the tool from the Styrmin image on a driver outside `/styrmin/drivers`. The author mounts the directory into the container. The documentation shows the command.

## Requirements *(mandatory)*

### Functional Requirements

The numbers FR-001 to FR-014 are the numbers of the brief. FR-015 to FR-017 are added by this spec.

- **FR-001**: `check` MUST run the same checks as a load from a local directory, with the same code and the same messages, without the prefix that the load adds, such as "Error while deserializing the driver resource: ", and apart from the messages that only the tool writes ([contracts/cli.md, "Message format"](contracts/cli.md#message-format)):
  - `driver.styrmin.yml` against the driver model;
  - the checks across fields of `driver.styrmin.yml` that the load runs after it: the documentation of environment variables and the backup configuration ([`loaders.py`](../../backend/styrmin_backend/services/driver/loaders.py#L74-L82)). The brief does not list these two checks; this spec adds them because the load runs them;
  - the syntax of `values.j2.yml`, and the retired template filters;
  - each action declared under `spec.actions` whose function is missing from `actions.py`.

  Verification: for each invalid driver that the backend's driver tests use, `check` reports the message of the load and exits with 1.
- **FR-002**: The tool MUST build an example context from the driver directory:
  - the parameter defaults, components, services and Helm chart from `driver.styrmin.yml`;
  - for a parameter without a default, a placeholder value of its kind, and a warning that names the parameter. Added by the plan ([research R-006](research.md#r-006-placeholder-values-for-parameters-without-a-default)): `generic-app` and `infrahub-mcp` each declare one parameter without a default and use it in `values.j2.yml`, so without a placeholder they would fail SC-001;
  - `default_version` as the **application version**;
  - placeholder values for the cluster, environment, deployment and instance.

  Verification: `styrmin-driver context` on `simple-app` prints the parameter defaults and the services that its `driver.styrmin.yml` declares, and `context` on `generic-app` prints a placeholder for `image_repository` and a warning.
- **FR-003**: An author MUST be able to give a context file that holds only the values to change. The tool merges it into the example context: nested keys are merged, and lists are replaced.
  Verification: a file that sets one parameter changes only the values that come from that parameter in the rendered output.
- **FR-004**: The tool MUST reject a context file whose merged result does not match the context model, name the key, and exit with 2. The context model rejects unknown keys ([`GlobalContext`](../../backend/styrmin_backend/context/models/contexts.py#L121-L123), `extra="forbid"`).
  Verification: a context file with a mistyped key gives exit code 2 and the name of the key.
- **FR-005**: `styrmin-driver context <dir>` MUST print the full example context, so the author can view every value that a template can use.
  Verification: the output validates against the context model.
- **FR-006**: The example context MUST contain every key that a real context contains for the same driver, including utilities such as the ingress.
  Verification: in the E2E test, the example context of `simple-app` has every key of the context in the `StyrminDeployment` resource of its deployment.
- **FR-007**: A use of an undefined variable that the render reaches MUST be an error that names the file, the line and the variable when the template writes it out, tests it in an `if`, loops over it, compares it, uses it in an operation, reads a name or an item of it, or passes it to a filter, a test, a function or a method. The render MUST use the server's undefined values, so that it fails where the server's render fails, with the server's message. Some uses are not reported, for example `parameters.x in parameters`, `[parameters.x] | length` or a slice bound. The `default()` filter and the `is defined` and `is undefined` tests are allowed. A variable is undefined when its name is neither a field of the context model nor a key that the context holds. A field of the context model that has no value, such as `instance.config.fqdn_suffix` when no FQDN suffix is set, is not an error: it renders as the agent renders it, as an empty string that tests as false ([research R-004](research.md#r-004-a-field-of-the-context-model-without-a-value-is-not-an-error)).
  Verification: `{{ parameters.admn_email }}` on line 12 gives an error that names `values.j2.yml`, line 12 and `parameters.admn_email`. `{% if instance.config.fqdn_suffix %}` with no suffix set gives no error, and the output equals the agent's output.
- **FR-008**: A template syntax error MUST name the file and the line.
  Verification: an unclosed `{% if %}` gives an error with the file and the line.
- **FR-009**: `check` MUST report in one run the problems of each check that can run, so that it can report more errors in one run than a load, which stops at the first: for example several invalid fields of `driver.styrmin.yml`, each on its own line, every action whose function is missing, and the undefined variables that the render finds. Some errors hide others, and `check` need not report them in the same run:
  - the checks of `driver.styrmin.yml` call the load's code, which stops at some errors, for example at the first invalid environment variable name; the checks across its fields run only when the driver model is valid; a YAML syntax error in the file also stops the checks of `actions.py`;
  - a syntax error in `values.j2.yml` or `actions.py` stops the other checks of that file;
  - the render runs only when `driver.styrmin.yml` matches the driver model and the template syntax is valid. It reports the undefined variables that it finds, stops where the server's render fails, and takes only some branches of the template.
  Verification: a driver with an invalid field and a missing action function gets both errors in one run.
- **FR-010**: Load warnings, such as an invalid `spec.info.icon`, MUST be printed and MUST NOT change the exit code.
  Verification: an invalid `spec.info.icon` gives a warning and exit code 0.
- **FR-011**: `diff` MUST compare values, not text. It reads both files as YAML, sorts the keys, writes both in the same format and shows a unified diff. A different key order, indentation or quoting is not a difference. A change of type, for example from `"8080"` to `8080`, is a difference, because Helm receives a different value.
  Verification: a base file with reordered keys gives exit code 0, and a change of type gives exit code 1.
- **FR-012**: Every command MUST exit with:
  - 0 when the driver passes or the values are the same;
  - 1 when the driver has errors or the values differ. A directory without `driver.styrmin.yml` gives 1;
  - 2 when the command cannot run: the directory does not exist, an option is unknown, a context file or base file cannot be read or is not valid YAML, or the merged context does not match the context model.

  With 2 separate from 1, CI can tell an invalid driver from a command that could not run.
  Verification: one test for each exit code of each command.
- **FR-013**: The commands MUST NOT need a Styrmin server, database, cluster or network access.
  Verification: the unit tests of the tool run with network access turned off.
- **FR-014**: Authors MUST be able to run `styrmin-driver` from a clone of the repository with `uv run styrmin-driver`, and from the Styrmin image.
  Verification: `docker run --rm <image> styrmin-driver check /styrmin/drivers/simple-app` exits with 0. The image already contains the example drivers in `/styrmin/drivers` ([`Dockerfile`](../../docker/Dockerfile#L61-L62)), and it installs the SDK through `cli`, which depends on `styrmin-sdk` ([`Dockerfile`](../../docker/Dockerfile#L46-L50), [`pyproject.toml`](../../pyproject.toml#L8-L11)).
- **FR-015**: The tool, the server's driver load and the agent's render MUST use one copy of the code that reads, checks and renders a driver directory, so that a change to a rule applies to all three. The backend MUST NOT keep a second copy of the moved code.
  Verification: the backend's existing driver load and render tests pass with the same expected messages, and a review of the change finds no second copy of the moved checks in `backend/styrmin_backend`.
- **FR-016**: The server's behavior MUST NOT change: a load still stops at the first error and returns the same messages, and the agent renders an undefined variable as it does today. `actions.py` files that import `styrmin_backend.actions` MUST keep working without changes.
  Verification: the backend's existing driver tests and the E2E tests that load and deploy the example drivers pass.
- **FR-017**: `render` MUST write only the Helm values to standard output. Errors and warnings go to standard error. When the render fails, the tool writes nothing to standard output.
  Verification: a successful render redirected to a file gives a file that parses as the values only, and a failed render gives an empty standard output.

### Key Entities

- **Driver directory**: the folder that holds `driver.styrmin.yml`, `values.j2.yml` and, when the driver declares actions, `actions.py`. The input of every command.
- **Example context**: the context that the tool builds from a driver directory (FR-002). Printed by `context`, and used by `check`, `render` and `diff` when the author gives no context file.
- **Context file**: a YAML file that the author writes and that holds only the values to change. The tool merges it into the example context (FR-003) and checks the result against the context model (FR-004).
- **Base values file**: a YAML file of Helm values, usually saved from an earlier `render`. `diff` compares it with the current render (FR-011).
- **Check error**: a problem that makes the driver invalid. It names the file and, when known, the line. Any check error gives exit code 1.
- **Load warning**: a message about a value that a load leaves out of the driver version, such as an invalid `spec.info.icon` ([`CONTEXT.md`, "Load warning"](../../CONTEXT.md#L125-L127)). It does not change the exit code.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The eight example drivers in [`driver/examples`](../../driver/examples) pass `styrmin-driver check`: `db-test`, `generic-app`, `infrahub`, `infrahub-enterprise`, `infrahub-mcp`, `semaphore`, `simple-app` and `slurpit`.
- **SC-002**: From a clone, or with the Styrmin image already pulled, an author goes from running `styrmin-driver check` to a first rendered output in less than one minute, with no Styrmin server, database or cluster.
- **SC-003**: `check` rejects every invalid driver that the backend's driver tests use, with the same message as the load.
- **SC-004**: For `simple-app`, `styrmin-driver render` with the context of a deployment gives the same values as the HelmRelease of that deployment.

## Testing Decisions

- E2E: one `api_only` test next to [`test_deploy_simple_app`](../../backend/tests/e2e/test_deploy_app.py#L45), on the same session deployment, so no new deployment starts ([constitution, section V, "Reuse before you boot"](../../dev/constitution.md)). The test:
  1. reads the context from the `StyrminDeployment` resource and the values from the HelmRelease;
  2. runs `styrmin-driver render` on `simple-app` with that context;
  3. checks that the two sets of values are equal (SC-004), and that the example context has every key of the deployment's context (FR-006).

  The test reads the context from the cluster because the GraphQL API returns only `contextDiff` for an instance, not its full context ([`schema.graphql`](../../schema.graphql#L641-L645)).
- Unit tests:
  - `check` on the eight example drivers (SC-001);
  - one invalid driver for each kind of error (FR-001, FR-007 to FR-010, SC-003);
  - the merge and the rejection of context files (FR-003, FR-004);
  - each exit code of each command (FR-012);
  - `diff` (FR-011);
  - standard output of `render` (FR-017).
- The unit tests of the tool run with network access turned off (FR-013).
- An image test runs `styrmin-driver check /styrmin/drivers/simple-app` in the Styrmin image (FR-014), as a step of the E2E node, which has the image that the session built ([research R-013](research.md#r-013-e2e-test-on-the-session-deployment-of-simple-app)).

## Documentation

These changes ship with the implementation ([constitution, section VII](../../dev/constitution.md)):

- `docs/docs/drivers/creating-a-driver.md`, step 9 "Load and test": add `check` and `render` before the load.
- A new reference page for `styrmin-driver` under `docs/docs/reference/`.
- `python_sdk/AGENTS.md`, for the new role of the SDK.
- An ADR for the backend's dependency on the SDK.
- `dev/knowledge/architecture.md`, for the move of the driver code to the SDK.
- `CONTEXT.md`, with the entries **Driver CLI / styrmin-driver** and **Example context**, and the sentence added to **SDK / styrmin-sdk**, in the wording of the brief. They are added in the change that implements the tool, because the glossary must match the code.
- A towncrier news fragment in `changelog/` for issue #23.

## Governance Gates

From the "Ask First" list in [`AGENTS.md`](../../AGENTS.md):

- New dependencies: crossed.
  - Jinja2 becomes a direct dependency of the SDK. It is already in [`uv.lock`](../../uv.lock#L1102), at version 3.1.6.
  - The backend depends on the SDK, which is a member of the same workspace.
  - No new package is expected in `uv.lock`. The plan checks it.
- Database schema or migrations: not crossed.
- GraphQL schema: not crossed.
- CI/CD workflows: not crossed in the first version. Publishing the SDK to PyPI would cross it.
- Authentication or authorization: not crossed.
- E2E coverage: not skipped. See "Testing Decisions".

## Assumptions

- The feature is still wanted. Fatih confirmed it on Slack on 2026-10-28, according to the brief.
- The driver model and the context model move to the SDK with the checks and the renderer, and `styrmin_backend.actions` keeps giving `GlobalContext` to `actions.py` files through a re-export ([research R-001](research.md#r-001-what-moves-to-the-sdk-and-under-which-package), [R-002](research.md#r-002-the-backend-keeps-its-import-paths-through-re-export-modules-and-one-error-base)).
- The SDK package requires Python 3.12 or later ([`python_sdk/pyproject.toml`](../../python_sdk/pyproject.toml#L5)), and the workspace requires Python 3.14 ([`pyproject.toml`](../../pyproject.toml#L7)). Not known: whether the moved code uses features of Python 3.13 or 3.14. The plan checks it, and either keeps the SDK at 3.12 or raises its minimum.
- `diff` takes `--context` as an option, as `render` does, and uses the example context without it. The brief shows the option in its example and does not say that it is required.
- When `render` fails, it writes nothing to standard output (FR-017). The brief says that errors go to standard error and does not say what standard output holds on failure. This spec chooses an empty output, so that a redirected failure does not leave a partial values file.
- A base file that cannot be read gives exit code 2, as a context file does (FR-012). The brief names only the context file.

## Out of Scope

Each item is a candidate follow-up issue.

- `helm template` of the chart with the rendered values, and the checks on its output: components against workloads, component containers, service ports and network access. These need `helm` and internet access.
- A check that each image tag exists in its registry.
- The server rejecting undefined variables. This would break drivers that load and work today.
- Publishing the SDK to PyPI.
- `check_driver.py` in the `creating-styrmin-drivers` skill calling `styrmin-driver` instead of using its own copy of the rules.
- Offline commands in `styrminctl`.
- A deployment manifest (`styrmin/v1`) as the context input. The tool would have to repeat how the server merges the cluster, environment and deployment configuration, and on the server that merge reads stored records.
- JSON output. The brief says this was not discussed.

## Sources

- The brief on issue #23: [comment 6466328637](https://github.com/opsmill/styrmin/issues/23#issuecomment-6466328637), written on 2026-10-28, which records the decisions that Simon made on 2026-10-28 in a review of the issue.
- Issue [#23](https://github.com/opsmill/styrmin/issues/23).
- The code and documentation of commit [`8f450f6`](https://github.com/opsmill/styrmin/commit/8f450f6978a36bc1f6ea86c09fb99a47bb4ad904) on `develop`, linked above.
- A Slack message from Fatih on 2026-10-28, in a direct conversation, with no link. Reported by the brief.
- `check_driver.py` in the `creating-styrmin-drivers` skill, which is not in a repository that can be linked. Reported by the brief.
- An anonymous token request and manifest request to `registry.opsmill.io` on 2026-10-28, for the answer on image credentials.
