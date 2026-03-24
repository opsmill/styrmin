import json

import yaml
from invoke import Context, task

from .utils import KIND_CLUSTER_NAME, KUBERNETES_ROOT_NAMESPACE, MAIN_DIRECTORY_PATH, TASKS_DIRECTORY_PATH, print_header

KIND_IMAGES_FILE = TASKS_DIRECTORY_PATH / "docker-images.yml"
DEV_LOCAL_DIR = MAIN_DIRECTORY_PATH / "dev" / "local"


@task
def delete(context: Context) -> None:
    """Delete the Kind cluster."""
    print_header(f"Deleting the {KIND_CLUSTER_NAME} cluster...")
    context.run(f"kind delete cluster --name {KIND_CLUSTER_NAME}", pty=True)


@task
def create(context: Context) -> None:
    """Create the Kind cluster."""
    print_header(f"Creating the {KIND_CLUSTER_NAME} cluster...")
    context.run(f"kind create cluster --name {KIND_CLUSTER_NAME} --config docker/kind-config.yml", pty=True)


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


def _read_images() -> list[str]:
    """Read the list of images from the docker-images YAML file."""
    return yaml.safe_load(KIND_IMAGES_FILE.read_text())["images"]  # type: ignore[no-any-return]


class _IndentedListDumper(yaml.Dumper):
    """YAML dumper that indents list items under mapping keys."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:  # noqa: ARG002
        return super().increase_indent(flow, False)


def _write_images(images: list[str]) -> None:
    """Write the list of images to the docker-images YAML file."""
    KIND_IMAGES_FILE.write_text(
        yaml.dump(
            {"images": sorted(set(images))},
            Dumper=_IndentedListDumper,
            default_flow_style=False,
            sort_keys=False,
            explicit_start=True,
        )
    )


@task
def sync_images(context: Context) -> None:
    """Discover images in the Kind cluster and add missing ones to docker-images.yaml."""
    result = context.run(
        f"docker exec {KIND_CLUSTER_NAME}-control-plane crictl images -o json",
        hide=True,
    )
    if not result:
        return

    cluster_images_data = json.loads(result.stdout)
    cluster_refs: set[str] = set()
    for img in cluster_images_data.get("images", []):
        cluster_refs.update(img.get("repoTags", []))

    known_images = _read_images()
    known_set = set(known_images)

    new_images = sorted(cluster_refs - known_set)
    if not new_images:
        print("All cluster images are already in docker-images.yaml")
        return

    print(f"Adding {len(new_images)} new image(s):")
    for image in new_images:
        print(f"  + {image}")

    _write_images(known_images + new_images)


def _get_docker_platform(context: Context) -> str:
    """Get the Docker daemon's OS/Arch (e.g. ``linux/amd64``)."""
    result = context.run(
        "docker version --format '{{.Server.Os}}/{{.Server.Arch}}'",
        hide=True,
    )
    if not result:
        msg = "Failed to detect Docker platform"
        raise RuntimeError(msg)
    return result.stdout.strip()


def _get_kind_node_images(context: Context) -> set[str]:
    """Return the set of image references already present on the Kind node."""
    result = context.run(
        f"docker exec {KIND_CLUSTER_NAME}-control-plane crictl images -o json",
        hide=True,
        warn=True,
    )
    if not result or result.failed:
        return set()
    node_images: set[str] = set()
    for img in json.loads(result.stdout).get("images", []):
        node_images.update(img.get("repoTags", []))
    return node_images


@task
def load_images(context: Context) -> None:
    """Load Docker images into the Kind cluster.

    Uses ``docker save --platform | kind load image-archive`` instead of
    ``kind load docker-image`` to work around issues with the containerd
    image storage backend.  Images already present on the Kind node are
    skipped.
    """
    platform = _get_docker_platform(context)
    node_images = _get_kind_node_images(context)
    images = _read_images()
    for image in images:
        if image in node_images:
            print_header(f"Skipping {image} (already on node)")
            continue
        result = context.run(f"docker image inspect {image}", warn=True, hide=True)
        if not result or result.failed:
            print_header(f"Pulling {image} ...")
            context.run(f"docker pull {image}", pty=True)
        print_header(f"Loading {image} ...")
        save_cmd = f"docker save --platform {platform} {image}"
        load_cmd = f"kind load image-archive --name {KIND_CLUSTER_NAME} /dev/stdin"
        result = context.run(f"{save_cmd} | {load_cmd}", warn=True, pty=True)
        if not result or result.failed:
            context.run(f"docker save {image} | {load_cmd}", pty=True)
