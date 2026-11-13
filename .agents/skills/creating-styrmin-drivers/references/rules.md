# Rules that decide whether a driver works

Each rule comes from a deployment that failed. `scripts/check_driver.py` checks most of them. Do
not skip one because the chart "probably" handles it.

1. **Use the application's existing Helm chart**, preferably the official one. Pin its exact
   version, and check that the version exists (`helm show chart ... --version X`). Never write a chart.
2. **Ship a NetworkPolicy that allows egress.** Styrmin puts `default-deny-egress` in every
   deployment namespace. Without your own policy, no pod can resolve DNS or reach its database, and
   the deployment times out. Allow DNS, the pods of the same namespace, and the internet only when
   the application needs it. See [references/networking.md](networking.md).
3. **Set `fullnameOverride: styrmin-<name>`** on the main chart and on every subchart. The release
   name is `styrmin-<deployment uuid>` (44 characters), so generated names pass the 63-character
   limit. Use these names, with the chart's suffixes (`-master`, `-primary`, ...), as hostnames in
   the application's settings: read the rendered Service names, do not guess them.
4. **Fixed credentials, never generated ones.** Passwords, secret keys and API tokens come from the
   values template or from parameters with defaults, not from `randAlphaNum` or a chart default
   that generates them. A restored or cloned deployment must still match its data.
5. **Image tags follow the registry, not the app version.** Map `{{ app.version }}` to the exact tag
   format (`v{{ app.version }}`, `{{ app.version }}-alpine`, ...) and let `--check-images` prove it
   exists. Bitnami stopped publishing versioned tags under `docker.io/bitnami` in 2025: point Bitnami
   subcharts at `docker.io/bitnamilegacy/<image>` with an existing tag, or at another image.
6. **One external service, one URL.** Declare the web UI or API as a service with `scope: external`,
   and enable the chart's Ingress with the host `{{ services['<service>'].primary_fqdn }}` (add
   `human_readable_fqdn` as a second host). Do not set the ingress class: Styrmin sets it.
7. **Component labels must be on the workload and on its pods.** `identifier.label` must match the
   `metadata.labels` of the Deployment or StatefulSet *and* its pod template labels. Styrmin selects
   the workloads to stop, start, scale and patch by the **first** label only: put first a label that
   no other workload has. `container` must be the exact name of the application container in the
   rendered chart.
8. **Do not pass env vars, replica counts, image overrides, command or args to the chart.** Styrmin
   applies them to the component container after the chart renders. Use `replicas` / `singleton`
   on the component instead of a parameter.
9. **Storage class from the context**: `{{ instance.config.standard_storage.storage_class }}`.
   Read every cluster and environment setting from `instance.config`, never hard-code them.
10. **Be Ready within 270 seconds, and never later than 300.** Styrmin shows the deployment as
    failed when its pods are not Ready 270 s after the rollout starts; it turns to running if
    they become Ready later. At 300 s FluxCD fails the install and rolls it back, which deletes
    the pods. Do not add long `initialDelaySeconds`. When the application migrates its database
    on first start, give the startup probe enough attempts for the migration, and say in the
    README that the first start is slow.
11. **Quote every version**: `version: "1"`, `supported_versions: ">=4.1,<4.5"`,
    `default_version: "4.4.2"`, `helm.main.version: "7.1.0"`. Versions are PEP 440, without `v`.
    `default_version` must be inside `supported_versions`, and the range must contain only versions
    the pinned chart supports.
12. **Undefined template variables render as empty strings, silently.** A typo such as
    `services.netbox.primary_fqdn` for a service named `web` gives an empty host. The check script
    reports each one.
13. **No actions unless Helm cannot do the step.** Most drivers need none. An `upgrade` action with
    `mode: core` replaces Styrmin's upgrade, so it must call `upgrade_deployment_version`.
14. **Do not name a chart Service like a driver service.** Styrmin creates a Service named after each
    `spec.services[].name` in the namespace.
15. **Never invent a value** (chart name, repository URL, value key, image tag, port, label). Read it
    from the chart (`helm show values`, `helm template`) or the registry. When you cannot verify a
    value, say so in the README.
16. **Containers that call the Kubernetes API fail.** Styrmin's network policies block the
    Kubernetes API, and a portable NetworkPolicy cannot open it. Init containers that wait with
    `kubectl`, and sidecars that watch ConfigMaps or Secrets (`kiwigrid/k8s-sidecar`, used for
    configuration reload or dashboards), never become ready. Turn them off with the chart's values;
    the worker then restarts a few times until the web server has migrated the database. A pod
    whose service account gets a Role or ClusterRole in the chart probably calls the API: the
    check warns about it. Features built on the API, such as Jenkins agents started as pods,
    cannot work under Styrmin: turn them off and say so in the README.
17. **Hosts the chart builds from the release name.** Some charts wire a subchart into the
    application with a host built from the release name (`<release>-postgresql`), ignoring the
    subchart's `fullnameOverride`. The Service is then `styrmin-postgresql` and the application
    never connects. The scaffold and the check report such hosts. Set the host explicitly in the
    application's settings when the chart keeps a value you set, or turn the subchart off when the
    application runs without it. Do not remove the `fullnameOverride`: names built from the
    44-character release name pass the limits (a StatefulSet name must stay under 53 characters,
    because Kubernetes adds a hash to it in a 63-character pod label).
18. **Use an OCI location when the repository points to one.** Some HTTP repositories (Bitnami)
    list each chart version with an `oci://` URL. The Helm command follows it, but FluxCD, which
    Styrmin uses to install charts, cannot: the install never starts ("unsupported protocol scheme
    oci"). Use the OCI location (`oci://registry-1.docker.io/bitnamicharts/<chart>`). The scaffold
    does it, and the check FAILs on the HTTP location.
19. **Every Secret and ConfigMap a pod needs must exist.** A chart that reads a password from an
    "existing secret" by default (for example a database password Secret) does not create it. The
    pod then stays in `CreateContainerConfigError`. Set the values that make the chart create the
    Secret (an inline password), or point the setting at a Secret the chart creates. The check FAILs
    on each missing Secret or ConfigMap.
20. **A list value replaces the chart's list.** Helm merges maps but not lists: when you set
    `extraVolumes`, `extraVolumeMounts`, `env` or a similar list, the chart's default entries are
    gone. The authentik chart mounts a socket volume into its PostgreSQL subchart this way; a
    driver that set only the `backup` volume removed it, and PostgreSQL stopped with "Read-only
    file system". Copy the chart's default entries into your list (the parent chart's values for
    a subchart win over the subchart's own). The check FAILs when a volume, mount or env list
    drops a default entry.
21. **Change only what the driver needs.** Keep the chart's defaults for everything else. A
    default you turn off "to keep it simple" can break the application in a way no offline check
    sees: with the Bitnami Keycloak chart 25.2.0, `cache.enabled: false` makes Keycloak 26.3.3 stop
    at start ("Incomplete line .../conf/"). Turn a feature off only for a reason you can name
    (rules 16, 17), and write the reason in the README.
22. **The application must be ready to use after the deployment.** When the application asks
    first-run questions in the browser that its configuration can answer, answer them with its
    settings. Uptime Kuma 2 asks which database to use unless `UPTIME_KUMA_DB_TYPE` is set; a
    driver without it deploys, but users find a setup page. Read the application's documentation
    for its environment variables (database type, admin user, base URL). What users must still do
    in the browser (for example create the first user) goes in the README.
23. **The URL must answer while the application waits for its operator.** Some applications
    start in a state that only an operator can end: a new Vault is uninitialized and sealed until
    someone runs `vault operator init` and unseals it. Their default readiness probe fails in
    that state, so the pod is never Ready, the Ingress has no backend, and the URL answers 503
    "no available server": users cannot reach the page or API they need to finish the setup.
    Make the readiness probe accept the waiting state (Vault chart:
    `server.readinessProbe.path: "/v1/sys/health?standbyok=true&sealedcode=204&uninitcode=204"`)
    rather than turning probes off, and say in the README what the operator must do.
