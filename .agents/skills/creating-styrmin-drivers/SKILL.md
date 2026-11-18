---
name: creating-styrmin-drivers
description: 'Writes a Styrmin application driver (driver.styrmin.yml, values.j2.yml, and actions.py only when needed) for an application that has a Helm chart, and checks it offline with a bundled script, and with the styrmin-driver command of Styrmin when it is available, until it passes. TRIGGER when: the user asks to make, create, write or package a Styrmin driver for an application ("make a styrmin driver for NetBox", "we need a driver to deploy X on Styrmin"). DO NOT TRIGGER when: deploying or upgrading an application with an existing driver, changing Styrmin itself, or writing a plain Helm chart.'
compatibility: Needs helm 3, Python 3.10+ with PyYAML, Jinja2 3.1.6 or later and packaging (or uv), and internet access to read the chart and the image registries. Targets Styrmin 0.1.59 and later (from 0.1.59 Styrmin builds the Ingress of an external service).
metadata:
  version: '0.1.16'
  author: OpsMill
---

# Creating Styrmin drivers

A Styrmin **driver** tells Styrmin how to deploy and operate one application on Kubernetes with an
**existing Helm chart**. Styrmin renders the driver's values template with a **context** (the
deployment's namespace, URLs, storage class, application version, parameters), installs the chart
with FluxCD, patches the result (labels, env vars, replicas, ingress class), builds the Ingress of each external
web service, and runs the driver's optional lifecycle actions.

A driver is a directory:

```text
<app>-driver/
├── driver.styrmin.yml   # required: metadata, chart, components, services, parameters, actions
├── values.j2.yml        # Jinja2 template that renders the chart's Helm values
├── actions.py           # only when the spec declares actions
└── README.md            # how to load and deploy it, credentials, what was checked
```

**Done means:** `scripts/check_driver.py <driver-dir> --check-images` reports **0 FAIL**, `styrmin-driver check`
(step 6) reports no errors or the final report says it did not run, every WARN is fixed or explained in the
README, and the final report states what is verified and what is not.

## Start here

Run these four steps first, in this order, before you read anything else (not the references,
not the example, not the scripts' code):

```bash
S=<skill-dir>/scripts                      # the folder of this SKILL.md, then /scripts
# 1. Find the official chart: its location and latest version
python3 $S/find_chart.py <application>
# 2. Summarize it (about 150 lines; full files go to /tmp/chart)
python3 $S/chart_summary.py <location> <chart-version> --out /tmp/chart
# 3. Write the first draft of the driver
python3 $S/scaffold_driver.py <driver-dir> <driver-name> <location> <chart-version>
# 4. Check it, then fix what the output and `grep -n TODO <driver-dir>/*` list, and repeat
python3 $S/check_driver.py <driver-dir> --keep /tmp/check
```

`<location>` is `<repo-url>/<chart>` for an HTTP repository, or `oci://<registry>/<path>/<chart>`.
The rest of this page explains each step and how to resolve each TODO and FAIL.

## How to work

These habits decide whether you finish. They matter most for smaller models.

- **Draft early, then let the check script lead.** Do not research everything first. Run the
  summary, run the scaffold, run the check, then fix what the check and the TODO lines say. Each
  FAIL names the problem and the fix.
- **Run the scripts; do not read their code.** Their output says what to do. Reading them costs
  thousands of tokens and teaches you nothing you need: `check_driver.py --list-checks` prints
  what the check covers. Do not read the references or the example before step 4 either: a FAIL
  tells you which page to read.
- **Steps 1 to 3 take about 5 tool calls.** Find the chart, summarize it, scaffold the driver.
  Then work from the check output.
- **Do not look up image tags by hand.** `check_driver.py --check-images` checks every tag in the
  registry; change a tag only when it reports one missing.
- **Write longer scripts to a file, then run the file.** Use the file-writing tool for anything
  longer than a few lines instead of `python3 - <<'EOF'` in a shell command.
- **Use the chart's exact value paths.** Helm ignores a key the chart does not declare, without an
  error: `waitForBackend` at the top level does nothing when the chart reads
  `worker.waitForBackend`. Copy paths from the chart's `values.yaml`; the check script warns about
  keys the chart does not have and says where the key exists.
- **Keep notes in a file.** Write the facts you found (with their source) and your decisions in
  `NOTES.md` next to the driver directory, as you go. When your context is summarized, read
  `NOTES.md` first instead of searching again.
- **Keep your context small.** Never print more than about 150 lines at once: send long output to a
  file (`> file`) and read the part you need with `grep -n`, `sed -n 'START,ENDp'` or `head`. Read a
  reference page only when a step links to it. Avoid fetching web pages: `helm show` and the
  registry answer most questions.

## Workflow

Copy this checklist into `NOTES.md` and tick each item:

```text
- [ ] 1. Find the chart: repository, chart name, latest version
- [ ] 2. Summarize it: chart_summary.py
- [ ] 3. Draft the driver: scaffold_driver.py
- [ ] 4. Check the draft: check_driver.py
- [ ] 5. Resolve every TODO and every FAIL (sections A to F below)
- [ ] 6. check_driver.py --check-images: 0 FAIL, every WARN fixed or explained, no TODO left;
       then styrmin-driver check in a container
- [ ] 7. README.md
- [ ] 8. Final report
```

The scripts are in `<skill-dir>/scripts/` and need helm 3 and Python with PyYAML, Jinja2 and
packaging (`pip install pyyaml "jinja2>=3.1.6" packaging`).

### 1. Find the chart

```bash
python3 <skill-dir>/scripts/find_chart.py <application>
```

It lists the charts on Artifact Hub, official first, with their latest version, the application
version they ship, and the `<location>` to use. Take the official chart, else the one from the
application's own organization. When Artifact Hub has none, find the chart in the application's
documentation: the location is `<repo-url>/<chart>` or `oci://<registry>/<path>/<chart>`.

### 2. Summarize the chart

```bash
python3 <skill-dir>/scripts/chart_summary.py <location> <chart-version> --out /tmp/chart
```

When the chart refuses to render because it requires a value (the error names it), run the
script again with `--set <key>=<value>` and a fixed value, and pass the same `--set` to the
scaffold. It prints, in about 150 lines: the subcharts (with their `extraDeploy` and `networkPolicy` keys),
every workload with its labels, containers, images, ports, probes and volumes, the Services, and
the value keys drivers usually set. The full files are in `/tmp/chart/`: grep them for details.
Write the main facts in `NOTES.md`.

### 3. Draft the driver

```bash
python3 <skill-dir>/scripts/scaffold_driver.py <driver-dir> <driver-name> <location> <chart-version>
```

It writes `driver.styrmin.yml`, `values.j2.yml` and `README.md`: components with labels that
Styrmin can match, the external service, `fullnameOverride` for the chart and its subcharts,
storage classes from the context, the image tag from `{{ app.version }}`, backups for data stores,
the egress NetworkPolicy, and `TODO` lines for what only you can decide. Read the two files it
wrote (they are short), then continue.

When a `TODO architecture` line or your own choice changes which subcharts run (for example a
plain database instead of an HA cluster), run the scaffold again with the same arguments plus
`--force` and one `--set <key>=<value>` per switch, so that the components follow.

### 4. Check the draft

```bash
python3 <skill-dir>/scripts/check_driver.py <driver-dir> --keep /tmp/check
```

It validates the spec like Styrmin's loader, renders `values.j2.yml` with a realistic context,
runs `helm template`, and checks components, containers, services, ingress hosts, names, network
policies, backups and actions. The rendered manifests are in `/tmp/check/manifests.yaml`.

### 5. Resolve every TODO and every FAIL

`grep -n TODO <driver-dir>/*` lists what is left. Fix one thing, run the check again, repeat. The
sections below say how to resolve each kind.

**A. Credentials and application settings.** Give every password, secret key and API token a
fixed value in `values.j2.yml` ([rule 4](references/rules.md)), and keep a database password the same in the
application's settings and in the database subchart. Set what the application needs to start:
its database and cache hosts (the `styrmin-...` Service names in `/tmp/check/manifests.yaml`), its
admin user, its first-run choices such as the database type ([rule 22](references/rules.md)), and its
allowed hosts or base URL from the two hosts in B. Keep every other chart default
([rule 21](references/rules.md)). A `TODO host` line means
the chart builds a host from the release name: follow it ([rule 17](references/rules.md)).

**B. Ingress.** Styrmin builds the Ingress of each service that is `scope: external` with kind `http` or
`https` (named `styrmin-svc-<service>`, with the host `{{ services['<service>'].human_readable_fqdn }}` and,
for the first service of the driver when it has no ingress override, `{{ services['<service>'].primary_fqdn }}`). So the chart's own Ingress
must stay off: a chart Ingress for that service gives it two Ingresses on one host. Read the chart's default
`ingress` values: if it is off by default, write no `ingress:` block; if it is on, set it to off. Look for
`kind: Ingress` in `/tmp/check/manifests.yaml`, including subcharts. Do not set the ingress class. The URL users open is
`{{ instance.config.external_url_scheme }}://<host>` (see [references/context.md](references/context.md)). Give
both hosts to the application when it checks its host name (allowed hosts, base URL). A service that
is `scope: internal` gets no Ingress from Styrmin; a chart Ingress for it stays as it is.

**C. Images.** Keep the image tag format of the registry (`v{{ app.version }}` when tags start
with `v`). For Bitnami images, the scaffold's comments say whether the tag exists and give the
newest `docker.io/bitnamilegacy` tag to pin: choose one of the two, do not search the registry.
Turn off sidecars you do not need (metrics exporters). `--check-images` proves each tag exists.

**D. Network.** The scaffold puts the egress NetworkPolicy in an extra-objects value. When it could
not (a `TODO network` line), follow "When no value can carry the policy" in
[references/networking.md](references/networking.md): a single-container application moves to
the app-template chart ([examples/app-template/](examples/app-template/)). Turn off init
containers that call the Kubernetes API ([rule 16](references/rules.md)).

**E. Components and backups.** Keep a component for each part users must stop, start or scale.
Mark single-primary data stores `singleton: true`. Remove replica workloads you do not need (for
example a cache in replication mode: set it to standalone). Dump backups need the `backup` volume
at `/backup`: see [references/backups-and-actions.md](references/backups-and-actions.md).
Full schema: [references/driver-format.md](references/driver-format.md).

**F. Actions.** Most drivers need none. Add `actions.py` only for steps Helm cannot express:
[references/backups-and-actions.md](references/backups-and-actions.md).

The context keys you will use most ([references/context.md](references/context.md) has all of
them and a real example):

| Expression | Value |
|---|---|
| `{{ app.version }}` | application version of the deployment, for example `4.4.2` |
| `{{ services['<name>'].primary_fqdn }}` | the URL host of the deployment |
| `{{ services['<name>'].human_readable_fqdn }}` | a readable second host |
| `{{ instance.config.standard_storage.storage_class }}` | storage class for volumes |
| `{{ instance.config.external_url_scheme }}`, `external_url_port` | how users reach the URL |
| `{{ parameters.<name> }}` | a parameter declared in the spec |

### 6. Final check

```bash
python3 <skill-dir>/scripts/check_driver.py <driver-dir> --check-images
```

Done means 0 FAIL, every WARN fixed or explained in the README, and `grep -n TODO <driver-dir>/*`
prints nothing. Use `--app-version` to render other versions of your range.

Then run Styrmin's own `styrmin-driver check`, which applies the rules of a driver load with the code that
the Styrmin server uses. It needs Docker and a Styrmin image that has the command: the first release after
0.2.2 (0.2.2 and earlier do not have it). Run it in a container with no network, on a read-only copy of the
driver, because the command renders `values.j2.yml` without a sandbox and a template can run code:

```bash
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  -v "<absolute-driver-dir>:/work/driver:ro" \
  registry.opsmill.io/opsmill/styrmin:<version> styrmin-driver check /work/driver
```

Give the driver directory as an absolute path without `:` or `,`; Docker reads a relative one-word path as a volume name.

Fix each error it prints (it gives the file and the line). When Docker or such an image is not available,
skip this and write "styrmin-driver check not run" in the README and the final report. The reference page is
`docs/docs/reference/styrmin-driver.md` in the Styrmin repository.

### 7. README.md

Complete the README the scaffold wrote: what the driver deploys (components, chart and version,
images), how to load and deploy it, the default credentials and how to change them, the
parameters, your decisions and why, what the check script reported, and what you could not
verify (for example "not deployed on a cluster").

### 8. Final report

Report to the user: the files, the check result (FAIL and WARN counts, and the result of `styrmin-driver check`
or that it did not run), the decisions you made and why, and what is not verified. Never claim the driver was deployed if you only ran the checks.

## The rules in short

The check script enforces most of these; [references/rules.md](references/rules.md) explains each one.

- Ship an egress NetworkPolicy: Styrmin denies all egress, even DNS, in every deployment namespace.
- Fixed credentials, never generated ones; `fullnameOverride: styrmin-<name>` on the chart and every subchart.
- Declare the web UI as an `external` service and keep the chart's Ingress off: Styrmin builds its Ingress.
- Component labels are on the workload and its pods; the container name is exact.
- Never pass env vars, replica counts or image overrides to the chart; quote every version.
- Copy value paths from the chart's `values.yaml`: Helm ignores unknown keys without an error.
- Turn off containers that call the Kubernetes API (kubectl waits, k8s-sidecar); pods must be Ready within 270 s (300 s at most).
- Keep `fullnameOverride`; when the chart builds a host from the release name, set the host yourself.
- Use the chart's OCI location when its HTTP index points to one; every Secret a pod reads must exist.
- Change only what the driver needs; a list value replaces the chart's list, so copy its default entries.
- Answer the application's first-run questions with its settings (database type, admin user).
- The URL must answer while the application waits for its operator (a sealed Vault): adapt the readiness probe.
- Never invent a value: read it from the chart or the registry, or say it is not verified.

## Load and deploy (for the user, or when a Styrmin install is available)

```bash
styrminctl drivers load-version <git-url> <branch> --driver-directory <path/in/repo>
styrminctl deployments create <driver-name> <app-version> <environment> --cluster <cluster>
```

The highest `spec.version` wins when several loaded driver versions match; pass
`--driver-version-id <uuid>` to pin one. More in [references/troubleshooting.md](references/troubleshooting.md).

## Reference files

- [scripts/find_chart.py](scripts/find_chart.py): step 1, the official chart and its location
- [scripts/chart_summary.py](scripts/chart_summary.py): step 2, the chart's facts in about 150 lines
- [scripts/scaffold_driver.py](scripts/scaffold_driver.py): step 3, a first draft of the driver with TODO lines
- [scripts/check_driver.py](scripts/check_driver.py): steps 4 and 6, the offline checks
- [references/rules.md](references/rules.md): the rules, and the failure behind each one
- [references/driver-format.md](references/driver-format.md): every field of `driver.styrmin.yml` and what the loader refuses
- [references/context.md](references/context.md): the template context, with a real example
- [references/networking.md](references/networking.md): Styrmin's network policies and the policy to ship
- [references/backups-and-actions.md](references/backups-and-actions.md): backup strategies, actions and primitives
- [references/troubleshooting.md](references/troubleshooting.md): load and deploy errors, and their causes
- [examples/semaphore/](examples/semaphore/): a complete driver (web server + PostgreSQL subchart) that deployed and answered on its URL
- [examples/app-template/](examples/app-template/): Uptime Kuma on the app-template chart, for a single-container application whose own chart cannot carry a NetworkPolicy
