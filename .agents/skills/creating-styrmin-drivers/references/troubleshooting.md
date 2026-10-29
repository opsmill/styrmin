# Load and deploy errors

Each line: what you see, the usual cause, the fix.

| What you see | Cause | Fix |
|---|---|---|
| `Deployment did not reach Ready within 270s (phase: CreatingHelmRelease)` | pods not Ready 270 s after the rollout: blocked egress, image pull error, pending volume, slow first start | `kubectl -n styrmin-<id> get pods`, `describe`, `logs`; check the items below |
| pod `Init:0/1` or `CrashLoopBackOff`, logs say the host name cannot be resolved | no egress NetworkPolicy: DNS is blocked | ship the policy in references/networking.md |
| connection to the database times out | the policy does not allow the namespace's pods | add the `podSelector: {}` egress rule |
| `ImagePullBackOff`, `manifest unknown` | the tag does not exist (tag format, Bitnami tags removed from docker.io/bitnami) | fix the tag; run `check_driver.py --check-images` |
| `exec format error` | the image has no build for the node's architecture | pick an image built for amd64 and arm64 |
| PVC `Pending` | storage class does not exist | use `{{ instance.config.standard_storage.storage_class }}` |
| URL answers 404 | the Ingress has no host equal to `primary_fqdn`, or the service is not `external` | set the hosts from `services['<name>']` |
| URL answers 400 / "Bad Request" / CSRF error | the application rejects its host name | add both hosts to the application's allowed hosts / trusted origins |
| application cannot connect to `styrmin-...` host | the hostname does not match the rendered Service name | read the Service names in the rendered manifests |
| `COMPONENT_CONTAINER_NOT_FOUND` | `container` is not in the workload | use the container name from the rendered chart |
| deployment uses an older or other driver version | the highest `spec.version` wins | raise `spec.version`, or pin with `--driver-version-id` |
| `Duplicate service name` / service name already used | another deployment of the environment declares the same service | deploy in another environment |
| install fails: `resource ... already exists` | two charts render the same object name (often a NetworkPolicy) | rename one |
| `check_driver.py`: `Jinja syntax error` on a line with a Helm template string such as `{{ include ... }}` or `{{ .Release.Name }}` | Styrmin renders `values.j2.yml` with Jinja first, and Helm template strings use the same `{{` | write the string as `{% raw %}{{ ... }}{% endraw %}`, as the scaffold does for text from the chart |
| `check_driver.py`: `access to attribute ... is unsafe` | the template reads an internal attribute of a Python object (a name that starts with `_`, or one such as `mro`) | use only the context variables and filters in references/context.md |
| first start never finishes, liveness restarts the pod | probes kill the container during migrations | raise the startup probe's `failureThreshold`, keep the first start under 270 s |

Useful commands on a cluster:

```bash
kubectl -n styrmin-<deployment id> get pods,pvc,ingress,networkpolicy
kubectl -n styrmin-<deployment id> describe pod <pod>
kubectl -n styrmin-<deployment id> logs <pod> --all-containers
kubectl -n styrmin-<deployment id> get helmrelease -o yaml     # values Styrmin rendered
styrminctl tasks get <task id>                                  # the failed step and its error
```
