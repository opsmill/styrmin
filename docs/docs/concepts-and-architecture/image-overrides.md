---
title: Image overrides
sidebar_position: 7
description: Set a custom or patched image on one component of a deployment.
---

## Image overrides

A component's container image comes from the Helm chart bundled with
the deployment's driver version. An **image override** sets a different
image, such as a custom or patched build, on one component of one
deployment. The driver does not change. Styrmin applies the override
after the chart renders, to the component's **component container**.

### Before you start

- **The driver must declare a component container** for the component
  (`components.<name>.container`). The driver's **Components** tab shows
  it, or **None declared**. Every example driver declares one per
  component. See
  [Create a driver](../drivers/creating-a-driver.md#the-component-container).
- **Only the component container changes.** Other containers, init
  containers, and chart `Job`s, `CronJob`s, and `DaemonSet`s keep their
  chart images. Styrmin patches only `Deployment` and `StatefulSet`
  workloads.
- **Component scope only.** There is no environment-wide or
  deployment-wide image override, and no layering.
- **The cluster's nodes must be able to pull the image**: from a public
  registry, or from a private one that the nodes already have
  credentials for.
- **Permissions** are the same as for any other deployment config edit.

### Writing a reference

An override is one full image reference with an explicit tag or digest:

```text
registry.example/acme/app-patched:1.4.2
registry.example/acme/app-patched@sha256:<64 hex characters>
registry.example/acme/app-patched:1.4.2@sha256:<64 hex characters>
registry.example:5000/acme/app-patched:{{ app.version }}
```

A reference without a tag or digest is rejected: there is no implicit
`latest`.

Styrmin replaces the `{{ app.version }}` token with the deployment's
application version when it renders the reference. It replaces every
occurrence, and spaces inside the braces are optional. This is plain
substitution, not template rendering: any other `{{ … }}` or `{% … %}`
expression is rejected.

| Override | At application version `1.4.2` | After an upgrade to `1.5.0` |
|----------|---------------------------------|-----------------------------|
| `registry.example/acme/app-patched:{{ app.version }}` | `registry.example/acme/app-patched:1.4.2` | `registry.example/acme/app-patched:1.5.0` |
| `registry.example/acme/app-patched:1.4.2` | `registry.example/acme/app-patched:1.4.2` | `registry.example/acme/app-patched:1.4.2` (pinned) |

Use the token when the tags of your build follow the application
version. A literal tag or a digest **pins** the image: it stays the same
across application upgrades until you change it.

Styrmin checks the reference when you save it, both as written and with
the deployment's application version substituted. A rejected write
names the component and starts nothing.

Overrides are part of the deployment config: an environment clone copies
them to each counterpart deployment, where the same checks run.

### In the UI

1. Open the deployment, go to the **Settings** tab, and click
   **Update Settings**.
2. In **Component Overrides**, choose the component. If it has no
   override yet, click **Add override**.
3. Type the reference in **Image**. The field checks it as you type;
   while a reference is invalid, **Review & apply** stays disabled and
   names the component to fix.
4. Click **Review & apply** and confirm.

To clear the override, empty the **Image** field and apply. The next
reconciliation restores the chart's image.

The **Component Overrides** card on the **Settings** tab shows, for each
component, the stored reference, the resolved reference when the token
makes them differ, and an **applied** or **not applied** badge.

A component without a component container has no **Add override** button
and no **Image** field. If it still has an override (for example after a
driver upgrade removed the container), the card shows the override
read-only, marked **not applied**, with a button to remove it.

### With `styrminctl apply`

Set `image` on the component's entry in `spec.config.components`. Quote
the reference: YAML reads an unquoted `{` as the start of a map.

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-app
spec:
  driver: acme/my-driver
  version: "1.4.2"
  environment: production
  config:
    components:
      - name: server
        image: "registry.example/acme/app-patched:{{ app.version }}"
```

`spec.config` is replaced on every apply, so removing the `image` key
(or the component's entry) and applying again clears the override. An
omitted or empty `spec.config` is the exception: it keeps the stored
configuration. When the override you remove is the only setting left,
write `components: []` instead of deleting `spec.config`. See
[the `styrminctl` reference](../reference/styrminctl.md#manifest-specconfig-format).

### With the Python SDK or GraphQL

The override is `ComponentConfigInput.image` on `updateDeployment` (and
on `deploy`). Read it back from `Deployment.componentImageOverrides`:
`component`, `reference`, `resolvedReference`, `isOrphaned`, and
`isApplicable`.

```python
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import ComponentConfigInput, UpdateDeploymentInput

# The client reads its token from STYRMIN_TOKEN, or takes token=... explicitly.
async with StyrminClient(server_address="https://styrmin.example") as client:
    await client.deployments.update(
        deployment_id,
        input=UpdateDeploymentInput(
            components=[
                ComponentConfigInput(
                    name="server",
                    image="registry.example/acme/app-patched:{{ app.version }}",
                ),
            ],
        ),
    )

    deployment = await client.deployments.get(deployment_id)
    for override in deployment.component_image_overrides:
        print(override.component, override.resolved_reference, override.is_applicable)
```

`components` replaces every stored component block, and leaving `image`
out of a block clears it. Send the env vars, `command`, `args`, and
image of every component you want to keep.

### Upgrades

When you upgrade a deployment to a new application version, an override
with the token changes to the matching tag, and a pinned override keeps
its image.

- **The upgrade dialog warns you.** When at least one override that
  applies has no token, the dialog shows **Pinned image overrides**
  above the confirm button, with each component and its reference.
  Confirming upgrades the deployment anyway.
- **`styrminctl deployments apply` warns you too.** When a manifest
  changes an existing deployment's application version, it prints a
  line like this on stderr for each deployment with overrides that have
  no token, and the exit code does not change:

  ```text
  warning: my-app: pinned image override on server will not follow version 1.5.0 (no {{ app.version }} token)
  ```

  `apply` reads only the config, so it lists every override without a
  token, including one that does not currently apply.
- **Styrmin rejects an upgrade that makes a reference invalid.** If the
  target version makes a stored override invalid that applies in the
  target driver version (for example a version with a `+`, which a tag
  cannot contain), the upgrade fails with `INVALID_IMAGE_REFERENCE`
  before any lifecycle action runs. An override that does not apply
  there is never rendered, so Styrmin does not check it.
- **Driver upgrade actions receive your image.** `get_component_images`
  returns the component container's image first. The example drivers'
  `upgrade` actions build the image of their migration Job from it and
  the target version: with the token, the Job runs your build at the new
  version; with a pinned override, it runs your repository at the new
  version while the component stays pinned.
- **The override can go in the apply that changes the version.**
  `styrminctl deployments apply` checks an override against the target
  driver version. The upgrade action can start before the new override
  reaches the component's workload, so `get_component_images` takes the
  override from the deployment's new configuration, and the first
  migration Job already runs your build.
- **A driver upgrade keeps your overrides.** If the new driver version
  removes the component container, Styrmin keeps the override, reports it
  as not applicable, and does not apply it until a driver version
  declares the container again; `styrminctl deployments apply` warns
  about it. If the new driver version removes the component, an apply
  that still sets the override is rejected, while an upgrade from the UI
  or with `deployments update-version` keeps it as orphaned.

### When something goes wrong

| What you see | Why | What to do |
|--------------|-----|------------|
| The write fails with `INVALID_IMAGE_REFERENCE` | The reference does not match the image reference format, has no tag or digest, contains another template expression, or is invalid once the version is substituted | Fix the reference named in the error |
| The write fails with `UNKNOWN_COMPONENT_IMAGE_OVERRIDE` | The driver version does not declare that component | Check the component name |
| The write fails with `COMPONENT_CONTAINER_NOT_DECLARED` | The component has no component container in the driver version | Ask the driver author to declare one; removing a stored override always works |
| The deployment becomes `FAILED` with the message below | The driver declares a component container name that the chart does not render | The driver author fixes `components.<name>.container`; until then, clear the env vars and image override on that component |
| A pod stays in `ImagePullBackOff` or `ErrImagePull` and the deployment never becomes ready | A typo in the reference, or a private registry the nodes cannot pull from | Open the deployment's **Pods** tab to read the waiting reason, then fix the reference |
| A rebuilt image does not roll out | Styrmin does not change the chart's `imagePullPolicy`, so nodes keep a cached image under the same tag | Push rebuilt images under a new tag, or reference them by digest |

A wrong component container name produces this status message
(`COMPONENT_CONTAINER_NOT_FOUND`):

```text
Component 'server': component container 'wrong-name' was not found in its rendered workload.
Styrmin never adds a container; fix components.server.container in the driver specification file.
```

Styrmin never adds a container to a pod: the release fails instead, and
nothing is applied to the workloads. The failure appears within one or
two operator timer intervals (60 seconds each by default) after Flux
reports the failed release, on a new deployment and on an update of a
running one. The same check runs when only env vars target the
component.

### Restricting registries

Styrmin does not limit which registries a reference can name: anyone who
can edit a deployment's config can set any image that the nodes can pull
on a component. To allow only some registries, use a cluster admission
policy, such as a Kubernetes `ValidatingAdmissionPolicy`, Kyverno, or OPA
Gatekeeper.

### Rolling Styrmin back

Styrmin v0.1.46 and earlier reject a deployment config that contains an
`image` key. Clear every image override before you roll Styrmin back to
one of these releases.

### Limits

- **No registry mirror.** Redirecting every image of a release to
  another registry is a separate feature.
- **No image pull secrets.** The nodes must already be able to pull the
  image.
- **No partial overrides.** Write the whole reference; you cannot
  override only the registry, the repository, or the tag.
- **One image per component**, on the component container only.

### Next steps

- [Create a driver](../drivers/creating-a-driver.md#the-component-container):
  declare the component container.
- [`styrminctl` reference](../reference/styrminctl.md#manifest-specconfig-format):
  the format of the manifest `spec.config`.
- [Lifecycle hooks and actions](./hooks-and-actions.md): how upgrade
  actions read component images.
