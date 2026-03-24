"""Styrmin SDK resource namespaces."""

from styrmin_sdk.resources.clusters import ClusterResource
from styrmin_sdk.resources.deployments import DeploymentResource
from styrmin_sdk.resources.drivers import DriverResource
from styrmin_sdk.resources.environments import EnvironmentResource
from styrmin_sdk.resources.tasks import TaskResource

__all__ = [
    "ClusterResource",
    "DeploymentResource",
    "DriverResource",
    "EnvironmentResource",
    "TaskResource",
]
