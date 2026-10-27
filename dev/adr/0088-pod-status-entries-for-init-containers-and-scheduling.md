# ADR-088: A Pod Status Lists Its Init Containers and Why the Pod Is Not Scheduled, in `containerStatuses`

**Status**: Accepted
**Date**: 2026-10-27
**Source**: [issue #574](https://github.com/opsmill/styrmin/issues/574)
**Related**: [ADR-007](0007-pod-status-records-observed-state-not-declared-state.md) (pod statuses
record what the agent observes), [ADR-060](0060-steps-and-derived-task-result.md) decision 18 (the
pods that a failed operator-phase step names), [issue #207](https://github.com/opsmill/styrmin/issues/207)
(the last termination of a container)

## Context

When a rollout fails, the "Install or upgrade the HelmRelease" step and "Wait for the deployment to be
ready" name the pods that are not ready, read from the stored pod statuses (ADR-060). On Styrmin
0.1.54, the stored pod statuses left out three things:

- A pod that is not scheduled, for example because its volume claim names a storage class that does
  not exist, has no container statuses. Kubernetes gives the reason only in the pod's `PodScheduled`
  condition (`Unschedulable`) and its message. The agent stored the pod with an empty
  `containerStatuses` list.
- The agent read only `status.containerStatuses`. A failing init container, such as the Semaphore
  driver's `admin` container, was not stored, and the pod's container showed
  `waiting:PodInitializing` with 0 restarts.
- The agent kept the reason of a waiting container without the kubelet's message, which says, for
  example, that an image tag was not found or which secret is missing.

The step error also named a container only when its reason was in a fixed list of eight reasons.

`PodStatus.containerStatuses` is a `JSON` column and a `JSON` GraphQL field, and only the agent writes
it. A new pod-level field needs an Alembic revision, a GraphQL change, a propagation test and new SDK
types.

## Decision

The agent writes three kinds of entries into `containerStatuses`, in this order. Each entry has a
`kind` key:

1. `pod`: only when the pod's `PodScheduled` condition is `False`. `name` is `PodScheduled`, `state` is
   `waiting:<condition reason>`, and `message` is the scheduler's message. `ready` is false,
   `restart_count` 0, `image` empty and `started_at` null, so that code reading the older keys works.
   A container name cannot be `PodScheduled`, because Kubernetes container names are lower case.
2. `init`: one entry per `status.initContainerStatuses`, with the keys of a container.
3. `container`: one entry per `status.containerStatuses`, as before.

Every entry gains `message`: the kubelet's message of a waiting container, or null. The message of a
terminated container is not stored, because the container writes it and it can hold anything the
program printed. For the same reason, the message of `PostStartHookError` is not stored: the kubelet
quotes in it the output of the `postStart` hook command.

`restartCount` of the pod counts as `kubectl get pods` does: while the pod is not `Initialized`, the
restarts of its init containers; after that, the restarts of its containers and of its sidecar init
containers (`restartPolicy: Always`).

The step error lists each pod that has not finished, with these causes:

- for the `pod` entry: `<reason>: <message>`;
- for a container or an init container that waits or ended with any reason except `ContainerCreating`,
  `PodInitializing` and `Completed`: `<name>: <reason>: <message>`, with `init container <name>` for
  an init container. The message of `CrashLoopBackOff` is left out, because it only gives the back-off
  delay;
- for a container or an init container that is not ready and runs again after restarts:
  `<name>: running after <n> restarts`;
- for an init container that runs, is not ready and has not restarted, such as one that waits for a
  service that does not answer: `init container <name>: still running`. The pod cannot start its
  containers until the init container ends, so it is a cause even without a restart. A container that
  runs without restarts and is not ready, for example because its readiness probe fails, is not
  named.

Each message is put on one line and cut to 300 characters. The Pods tab shows the `pod` entry above
the containers, an `init` tag on init containers, and each message under its container.

## Alternatives considered

- **A pod-level `reason` and `message` field on `PodStatus`.** It keeps `containerStatuses` for
  containers only. It needs an Alembic revision, a GraphQL schema change with its propagation test,
  and new SDK types, for one condition. Not chosen for this fix; it stays open if a second pod-level
  value is needed.
- **A container entry for each declared container of a pod that is not scheduled, with the
  scheduler's reason as its state.** Kubernetes reports no state for these containers, so the entry
  would record a state that the agent did not observe (ADR-007). Rejected.
- **Keeping a fixed list of reasons and adding the new ones.** Each Kubernetes reason that the list
  misses, such as `RunContainerError` or `CreatePodSandboxError`, would again leave the error without a
  cause. Rejected in favour of leaving out only the reasons of a container that starts or has done its
  work.
- **Storing the last termination of each container (`lastState.terminated`).** It would give the exit
  code of a failing init container. It is the subject of #207, which also covers containers that run
  again, so it is left to that issue.

## Consequences

- A user can read why a pod is not scheduled, or which init container fails, in the failed step, in
  `styrminctl tasks get` and in the Pods tab, without `kubectl`.
- Scripts that read `containerStatuses` through the API or the SDK can find a `pod` entry and `init`
  entries. A script that treats every entry as a container must skip entries whose `kind` is `pod`.
- Rows stored by an older agent have no `kind` and no `message`. The step error and the Pods tab read
  them as containers, until the next report replaces them within about 5 seconds.
- The step error is longer when the kubelet's message is long, for example the registry error of an
  image pull. The Pods tab keeps the whole message.
- The scheduler's message says that a volume claim is unbound, not which storage class is missing:
  that name is only in the volume claim's events, which Styrmin does not read.
- The log of a failing init container, which holds the cause of the Semaphore failure (a DNS lookup
  that timed out), is not stored. [Issue #147](https://github.com/opsmill/styrmin/issues/147) covers
  container logs.

## Confirmation

- `TestExtractPodDataFailureCauses` and `TestExtractPodDataFromKind` in
  `backend/tests/unit/agent/test_status_reporter.py`. The second class runs the agent on three pods
  read from a kind cluster, kept in `backend/tests/helpers/pods/`.
- The `#574` tests in `backend/tests/unit/steps/test_operator_history_failures.py`.
- `test_failure_causes_of_kind_pods_reach_the_step_and_read_only` in
  `backend/tests/functional/graphql/test_step_failure_propagation.py`.
- `PodRow failure causes (#574)` in `frontend/src/pages/deployments/PodsTab/PodRow.test.tsx`.
- `test_pod_statuses_name_scheduling_and_init_container_failures` in
  `backend/tests/e2e/test_task_steps.py`: on a vCluster, a pod that no node accepts gets the `pod`
  entry, and a pod whose init container exits with an error gets its `init` entry and restarts.
