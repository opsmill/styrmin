import os

from invoke import Context, task

from .utils import KUBERNETES_ROOT_NAMESPACE, MAIN_DIRECTORY_PATH, VCLUSTER_NAME, print_header

DEV_LOCAL_DIR = MAIN_DIRECTORY_PATH / "dev" / "local"


@task
def delete(context: Context) -> None:
    """Delete the vCluster."""
    print_header(f"Deleting the {VCLUSTER_NAME} cluster...")
    config_flag = f" --config {vcluster_dir}" if (vcluster_dir := os.environ.get("VCLUSTER_DIR")) else ""
    context.run(f"vcluster delete {VCLUSTER_NAME} {config_flag}", pty=True)


@task
def create(context: Context) -> None:
    """Create the vCluster."""
    print_header(f"Creating the {VCLUSTER_NAME} cluster...")
    config_flag = f" --config {vcluster_dir}" if (vcluster_dir := os.environ.get("VCLUSTER_DIR")) else ""
    context.run(f"vcluster create {VCLUSTER_NAME} --driver=docker --connect=false{config_flag}", pty=True)


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
        f"helm install agent helm/agent -n {KUBERNETES_ROOT_NAMESPACE} --create-namespace --set agent.enabled=false --dependency-update",
        pty=True,
    )


@task
def velero(context: Context) -> None:
    """Install MinIO and Velero for local backup support."""
    print_header("Deploying MinIO for backup storage...")
    context.run(
        f"kubectl apply -f {DEV_LOCAL_DIR / 'minio.yaml'} -n {KUBERNETES_ROOT_NAMESPACE}",
        pty=True,
    )
    print_header("Waiting for MinIO to be ready...")
    context.run(
        f"kubectl rollout status deployment/minio -n {KUBERNETES_ROOT_NAMESPACE} --timeout=120s",
        pty=True,
    )

    print_header("Installing Velero via Helm...")
    context.run(
        "helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts 2>/dev/null || true",
        pty=True,
    )
    context.run(
        f"helm upgrade --install styrmin-velero vmware-tanzu/velero"
        f" -n {KUBERNETES_ROOT_NAMESPACE}"
        f" -f {DEV_LOCAL_DIR / 'velero-values.yaml'}"
        f" --wait --timeout 5m",
        pty=True,
    )

    print_header("Velero installed. Waiting for BackupStorageLocation to be available...")
    context.run(
        "kubectl wait --for=jsonpath='{.status.phase}'=Available"
        f" backupstoragelocation/default -n {KUBERNETES_ROOT_NAMESPACE} --timeout=120s",
        pty=True,
    )
