import os

from invoke import Context, task

from .utils import KUBERNETES_ROOT_NAMESPACE, MAIN_DIRECTORY_PATH, VCLUSTER_NAME, print_header

DEV_LOCAL_DIR = MAIN_DIRECTORY_PATH / "dev" / "local"
HELM_DIR = MAIN_DIRECTORY_PATH / "helm"


@task
def delete(context: Context) -> None:
    """Delete the vCluster."""
    print_header(f"Deleting the {VCLUSTER_NAME} cluster...")
    config_flag = f" --config {vcluster_dir}" if (vcluster_dir := os.environ.get("VCLUSTER_DIR")) else ""
    context.run(f"vcluster delete {VCLUSTER_NAME} --driver=docker{config_flag}", pty=True)


@task
def create(context: Context) -> None:
    """Create the vCluster."""
    print_header(f"Creating the {VCLUSTER_NAME} cluster...")
    config_flag = f" --config {vcluster_dir} " if (vcluster_dir := os.environ.get("VCLUSTER_DIR")) else ""
    context.run(f"vcluster create {VCLUSTER_NAME} --upgrade --driver=docker --connect=false{config_flag}", pty=True)


@task
def connect(context: Context) -> None:
    """Connect to the vCluster and export kubeconfig."""
    print_header(f"Connecting to the {VCLUSTER_NAME} cluster...")
    config_flag = f" --config {vcluster_dir}" if (vcluster_dir := os.environ.get("VCLUSTER_DIR")) else ""
    context.run(f"vcluster connect {VCLUSTER_NAME} --driver=docker{config_flag}", pty=True)


@task
def init(context: Context) -> None:
    """Install the cluster with the required CRDs."""
    print_header("Initializating the cluster ...")
    context.run(
        f"helm upgrade --install agent helm/agent -n {KUBERNETES_ROOT_NAMESPACE} --create-namespace --set agent.enabled=false --dependency-update",
        pty=True,
    )


@task
def traefik(context: Context) -> None:
    """Install the Traefik ingress controller as a ClusterIP service.

    Callers are expected to set up a port-forward to reach it from the
    host. We use ClusterIP uniformly across platforms so the demo flow
    is identical on Linux and macOS.
    """
    print_header("Installing Traefik ingress controller (service.type=ClusterIP)...")
    context.run(
        "helm repo add traefik https://helm.traefik.io/traefik 2>/dev/null || true",
        pty=True,
    )
    context.run("helm repo update traefik", pty=True)
    context.run(
        f"helm upgrade --install traefik traefik/traefik"
        f" -n {KUBERNETES_ROOT_NAMESPACE} --create-namespace"
        f" -f {DEV_LOCAL_DIR / 'traefik-values.yaml'}"
        f" --set service.type=ClusterIP"
        f" --take-ownership"
        f" --wait --timeout 5m",
        pty=True,
    )


@task
def garage(context: Context) -> None:
    """Install Garage for local S3-compatible backup storage."""
    print_header("Deploying Garage for backup storage...")
    context.run(
        f"kubectl apply -f {DEV_LOCAL_DIR / 'garage.yaml'} -n {KUBERNETES_ROOT_NAMESPACE}",
        pty=True,
    )
    print_header("Waiting for Garage to be ready...")
    context.run(
        f"kubectl rollout status deployment/garage -n {KUBERNETES_ROOT_NAMESPACE} --timeout=120s",
        pty=True,
    )
