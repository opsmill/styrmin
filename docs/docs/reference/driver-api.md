---
title: Driver API
sidebar_position: 4
description: Reference for the driver.styrmin.yml specification — every field, every action declaration, every context primitive.
---

## Driver API

:::info Stub page — to be generated

This page will be generated from the Pydantic models that validate
`driver.styrmin.yml` and the action declarations. The text below
describes the scope of the page, not its final content.

Until the generation step exists, these files define the driver
specification:

- [`backend/styrmin_backend/driver/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/driver):
  the Pydantic models of the driver specification.
- [`driver/DRIVERS.md`](https://github.com/opsmill/styrmin/blob/develop/driver/DRIVERS.md):
  the written description of the driver format.

:::

### Scope

The page will document each field of the `driver.styrmin.yml`
specification:

- `apiVersion`, `kind`, `metadata`
- `spec.version`: the application driver version
- `spec.supported_versions`: a semver specifier for the application
  versions this driver supports
- `spec.info`: the icon (logo URL), description and links shown on the
  driver pages; the authors and license
- `spec.helm.main`: the Helm chart reference (location, version, values
  template)
- `spec.components`: component definitions (label selectors, defaults)
- `spec.parameters`: typed inputs that users set
- `spec.services`: declared network endpoints. Each service has a `name`, a
  `kind` (`http`, `https`, `tcp` or `udp`), a `scope` (`internal` or
  `external`), a `port` and a `component`. See
  [Services and Ingresses](#services-and-ingresses).
- `spec.actions`: lifecycle action declarations (hook, mode, Python
  function, prompts)

It will also document the **action primitives** that driver actions can
call from Python (`stop_components`, `start_components`,
`execute_commands`, `upgrade_deployment_version`, ...).

### Services and Ingresses

Until the generated reference exists, these rules apply to every driver
author for `spec.services`:

- `scope: external` means that Styrmin builds the Ingress of the service. For
  each external service of `kind` `http` or `https`, Styrmin builds one Ingress
  named `styrmin-svc-<service name>` in the deployment's namespace, with the
  ClusterIP Service of the service as its backend. A service of `kind` `tcp` or
  `udp` gets no Ingress.
- `scope: internal` means that Styrmin builds no Ingress. The chart can render
  one, and Styrmin sets its class and annotations after the chart renders.
- The chart must not render an Ingress for an external service. If it does, the
  service has two Ingresses on the same host. See
  [Migrate a driver whose external service renders its own Ingress](../drivers/migrating-external-service-ingress.md).
- The Ingress has the readable host `<service name>-<environment name>.<fqdn suffix>`.
  The application address `<driver name>-<deployment id>.<fqdn suffix>` is on the
  Ingress of the first service in `spec.services`, and only when Styrmin builds an
  Ingress for that service: it is `external` and has kind `http` or `https`. When
  the first service is external with kind `tcp` or `udp`, no Styrmin-built Ingress
  has the application address.
- A deployment can override the ingress class and the FQDN suffix of one
  external service: see
  [Service ingress overrides](../concepts-and-architecture/service-ingress-overrides.md).
- A template reads `services['<name>'].primary_fqdn`,
  `services['<name>'].human_readable_fqdn` (with the override suffix when there is
  an override), `services['<name>'].ingress_class` and
  `services['<name>'].overridden`. See [The context](../drivers/context.md).

For the full explanation, see
[Create a driver](../drivers/creating-a-driver.md#step-6-declare-services) and
[Ingress and networking](../concepts-and-architecture/ingress-and-networking.md).

### Action primitives and the steps of a task

Until the generated reference exists, these rules apply to every driver
author:

- When the Job that `execute_commands` starts fails, Styrmin stores the
  end of the Job's output on the hook step that runs the action: the last
  200 lines, at most 64 KiB. Every signed-in user, including Read-only
  users, can read it on the deployment page and through the API. Do not
  print secrets, such as passwords or tokens, in action commands.
- When the flow run of an action crashes, its first log line of level
  `ERROR` becomes part of the error of its hook step, which the same
  users can read. Styrmin replaces the action's API token and some common
  forms of secrets in that line with `<redacted>`, but not every form, so
  do not write secrets to the logs of an action (see
  [Logs of a crashed action are shown on its hook step](../drivers/loading-drivers.md#logs-of-a-crashed-action-are-shown-on-its-hook-step)).
- `execute_commands` names its Job `<release reference>-job`, in the
  deployment's namespace, with the label `styrmin.io/action-job=true`.
  The Job ends at its first failed pod and stays in the cluster after it
  ends. The next `execute_commands` call on the same deployment, in the
  same action or in a later one, deletes that Job and its pods once the
  Job has ended (completed or failed), then creates its own Job. The hook
  step shows a line that names the deleted Job. An action can therefore
  call `execute_commands` several times, and each upgrade of a deployment
  can run its upgrade action again.
- The `execute_commands` call fails, and deletes nothing, when the Job of
  that name is still running, for example because another change of the
  deployment runs its action at the same time. It also fails when a Job
  of that name exists that no driver action created.
- `stop_components`, `start_components` and `upgrade_deployment_version`
  link the task they start to the hook step that runs the action. The
  deployment page lists the started task under that step, and the hook's
  task result includes the started task's result.
- API calls that an action makes through the Python SDK, instead of
  these primitives, are not linked: the tasks they start appear as
  separate entries, and the hook's task result does not include them.

See
[Lifecycle hooks and actions](../concepts-and-architecture/hooks-and-actions.md#steps-of-a-hook)
for the steps that each hook records.

### Generation source

- **Schema**: the Pydantic models in
  [`backend/styrmin_backend/driver/`](https://github.com/opsmill/styrmin/tree/develop/backend/styrmin_backend/driver)
- **Build step**: not defined yet; it will write Markdown from the
  Pydantic JSON schemas, with field descriptions taken from the model
  docstrings

### Related pages

- [Drivers → Create a driver](../drivers/creating-a-driver.md): how to
  write a driver, step by step.
- [Drivers → The context](../drivers/context.md): the data that every
  action and template receives.
- [Concepts and architecture → What is an application driver?](../concepts-and-architecture/what-is-a-driver.md):
  what a driver is and what it contains.
