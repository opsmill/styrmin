"""Primitives for Styrmin component lifecycle and command execution.

This module provides core task primitives for the Styrmin platform, enabling the starting and stopping
of deployment components and the execution of arbitrary commands as Kubernetes jobs. These tasks are
designed to be orchestrated within Prefect flows and interact with the Styrmin backend and Kubernetes
infrastructure using the provided global context.

Key functionalities:
- Start or stop specified deployment components via GraphQL mutations to the Styrmin backend.
- Execute custom shell commands as Kubernetes jobs within the deployment's namespace.

Context: Those primitives are intended to be exposed to the developer of a driver to pilot Styrmin
features during an application upgrade. Their API calls authenticate with the short-lived token
that the reconcile passes to each action in ``STYRMIN_TOKEN`` (ADR-059).
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from prefect import task

from styrmin_backend.agent.service.kubernetes.primitives import (
    get_component_env,
    get_component_images as _k8s_get_component_images,
    get_component_labels as _k8s_get_component_labels,
    run_job,
)
from styrmin_backend.agent.tasks.utils import API_TOKEN_ENV
from styrmin_backend.context.models.contexts import GlobalContext

# Seconds a finished ``execute_commands`` Job stays in the deployment namespace
# before the Kubernetes TTL-after-finished controller deletes it together with
# its pod. Long enough to read the logs of a failed command, short enough that
# Jobs do not pile up across hooks and upgrades (#374).
JOB_TTL_SECONDS_AFTER_FINISHED = 3600

_GRAPHQL_DIR = Path(__file__).resolve().parent


def _load_query(name: str) -> str:
    return (_GRAPHQL_DIR / f"{name}.graphql").read_text()


def _api_client() -> httpx.AsyncClient:
    """Client authenticated with the token the reconcile passed to this action (ADR-059)."""
    token = os.environ.get(API_TOKEN_ENV)
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"} if token else None
    )


async def _execute(
    client: httpx.AsyncClient, operation: str, variables: dict[str, Any]
) -> dict[str, Any]:
    """Run a GraphQL operation and return its ``data``; raise on GraphQL errors."""
    api_url = os.environ.get("STYRMIN_URL_API", "http://localhost:8000")
    response = await client.post(
        f"{api_url}/graphql",
        json={"query": _load_query(operation), "variables": variables},
    )
    data = response.json()
    if errors := data.get("errors"):
        raise RuntimeError(f"GraphQL error: {errors[0].get('message', errors)}")
    return data.get("data") or {}


async def _wait_for_task(
    client: httpx.AsyncClient,
    task_id: str,
    timeout: float = 300.0,
    poll_interval: float = 5.0,
) -> None:
    """Poll a task until it reaches a terminal state (success/failed)."""
    start = time.time()
    while time.time() - start < timeout:
        data = await _execute(client, "get_task", {"taskId": task_id})
        task_data = data.get("task") or {}
        status = task_data.get("status")
        logger.info(f"Task {task_id} status: {status}")
        if status == "success":
            return
        if status == "failed":
            raise RuntimeError(f"Task {task_id} failed: {task_data.get('message')}")
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


async def _run_task_mutation(
    operation: str, field: str, variables: dict[str, Any]
) -> None:
    """Run a mutation that returns a Task, then wait for that task to finish."""
    async with _api_client() as client:
        data = await _execute(client, operation, variables)
        if task_data := data.get(field):
            await _wait_for_task(client, task_data["id"])


@task(task_run_name="Stop Components {components}")
async def stop_components(components: list[str], context: GlobalContext) -> None:
    """Stop the specified components in the given context.

    Args:
        components (list[str]): A list of component names to stop.
        context (GlobalContext): The global context object.

    Raises:
        ValueError: If a component is not found in the context.
    """
    if context.components is None:
        raise ValueError("No components found in the context.")

    await _run_task_mutation(
        "stop_components",
        "stopComponents",
        {
            "deploymentId": str(context.instance.deployment_id),
            "components": components,
        },
    )


@task(task_run_name="Start Components {components}")
async def start_components(components: list[str], context: GlobalContext) -> None:
    """Start the specified components in the given context.

    Args:
        components (list[str]): A list of component names to start.
        context (GlobalContext): The global context object.

    Raises:
        ValueError: If a component is not found in the context.
    """
    if context.components is None:
        raise ValueError("No components found in the context.")

    await _run_task_mutation(
        "start_components",
        "startComponents",
        {
            "deploymentId": str(context.instance.deployment_id),
            "components": components,
        },
    )


def _validate_component(component_name: str, context: GlobalContext) -> str:
    """Validate a component exists and return its label selector.

    Args:
        component_name: The component name to validate.
        context: The global context object.

    Returns:
        The label selector string for the component.

    Raises:
        ValueError: If components are missing or the component is not found.
    """
    if context.components is None:
        raise ValueError("No components found in the context.")
    if component_name not in context.components:
        raise ValueError(
            f"Component '{component_name}' not found in context.components."
        )
    return context.components[component_name].config.identifier.label.label_selectable()


@task(task_run_name="Get Component Labels {component}")
async def get_component_labels(
    component: str, context: GlobalContext
) -> dict[str, str]:
    """Get the pod template labels from a component's Deployment or StatefulSet.

    Args:
        component: The component name (e.g., "server").
        context: The global context object.

    Returns:
        Dict of label key-value pairs from the pod template metadata.
    """
    label_selector = _validate_component(component, context)
    return await _k8s_get_component_labels(
        namespace=context.instance.namespace,
        label_selector=label_selector,
    )


@task(task_run_name="Get Component Images {component}")
async def get_component_images(component: str, context: GlobalContext) -> list[str]:
    """Get the container images from a component's Deployment or StatefulSet.

    Returns images from all containers in the pod template spec. When the
    component declares a component container present in the pod template, its
    image is element 0 (it carries any image override); the others keep their
    pod-template order.

    Args:
        component: The component name (e.g., "server").
        context: The global context object.

    Returns:
        List of container image strings.
    """
    label_selector = _validate_component(component, context)
    assert context.components is not None  # checked by _validate_component
    return await _k8s_get_component_images(
        namespace=context.instance.namespace,
        label_selector=label_selector,
        container=context.components[component].config.container,
    )


@task(task_run_name="Execute Commands {commands}")
async def execute_commands(
    commands: list[str],
    image: str,
    context: GlobalContext,
    env_from_component: str | None = None,
    labels_from_component: str | None = None,
) -> None:
    """
    Executes a list of commands as kubernetes job with the given context.

    Every call creates a new Job named ``<release_reference>-job-<suffix>`` in the
    deployment namespace and waits for it to finish, so an action can call this
    primitive as many times as it needs -- across hooks and across upgrades of the
    same deployment. Finished Jobs are garbage-collected by Kubernetes after
    ``JOB_TTL_SECONDS_AFTER_FINISHED`` seconds.

    Args:
        commands (list[str]): A list of commands to execute.
        image (str): The container image to use for the job.
        context (GlobalContext): The global context object.
        env_from_component (str | None): Name of a component whose environment variables
            should be copied into the job. The component's Deployment or StatefulSet is
            looked up by label selector, and env/envFrom are extracted from its pod
            template spec. Works even when the component is scaled to 0 replicas.
        labels_from_component (str | None): Name of a component whose pod template labels
            should be copied onto the job's pods. Useful for network policy compatibility.

    Raises:
        ValueError: If a component is not found or no matching K8s resource exists.
    """
    container_spec: dict = {
        "name": "user-job",
        "image": image,
        "command": commands,
    }

    template_metadata: dict = {}

    if env_from_component:
        label_selector = _validate_component(env_from_component, context)
        env, env_from = await get_component_env(
            namespace=context.instance.namespace,
            label_selector=label_selector,
        )

        if env:
            container_spec["env"] = env
        if env_from:
            container_spec["envFrom"] = env_from

    if labels_from_component:
        label_selector = _validate_component(labels_from_component, context)
        labels = await _k8s_get_component_labels(
            namespace=context.instance.namespace,
            label_selector=label_selector,
        )
        if labels:
            template_metadata["labels"] = labels

    body: dict = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            # ``generateName`` lets the API server append a unique suffix, so a
            # Job left over from a previous call (or a previous upgrade of the
            # same deployment) can never collide with this one (#374).
            "generateName": f"{context.instance.release_reference}-job-",
            "namespace": context.instance.namespace,
        },
        "spec": {
            "ttlSecondsAfterFinished": JOB_TTL_SECONDS_AFTER_FINISHED,
            "template": {
                "spec": {
                    "containers": [container_spec],
                    "restartPolicy": "Never",
                }
            },
        },
    }

    if template_metadata:
        body["spec"]["template"]["metadata"] = template_metadata

    await run_job(namespace=context.instance.namespace, body=body)


@task(task_run_name="Upgrade Deployment Version to {target_version}")
async def upgrade_deployment_version(
    target_version: str, context: GlobalContext
) -> None:
    """Upgrade a deployment to a new application version.

    Args:
        target_version (str): The target application version to upgrade to.
        context (GlobalContext): The global context object.

    Raises:
        ValueError: If the upgrade fails.
    """
    await _run_task_mutation(
        "update_deployment_version",
        "updateDeploymentVersion",
        {
            "deploymentId": str(context.instance.deployment_id),
            "version": target_version,
        },
    )
