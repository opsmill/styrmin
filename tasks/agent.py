import os

from invoke import Context, task

from .utils import KUBERNETES_ROOT_NAMESPACE, print_header

# Image reference used to tag the locally-built styrmin image. Defaults
# to the chart's default registry path so kubelet name-matches the
# locally-built image under `pullPolicy: IfNotPresent` (no registry
# pull). CI overrides STYRMIN_IMAGE_VER to a per-runner, per-commit tag
# so concurrent jobs on shared self-hosted runners don't stomp the same
# `:latest` reference. See `helm/styrmin/README.md` "Running against a
# locally-built image".
IMAGE_NAME = os.getenv("STYRMIN_IMAGE_NAME", "registry.opsmill.io/opsmill/styrmin")
IMAGE_VER = os.getenv("STYRMIN_IMAGE_VER", "latest")
IMAGE_REF = f"{IMAGE_NAME}:{IMAGE_VER}"


@task
def build_image(context: Context) -> None:
    """Build the agent Docker image."""
    print_header(f"Building the agent Docker image ({IMAGE_REF})...")
    context.run(
        f"docker build -t {IMAGE_REF} -f docker/Dockerfile .",
        pty=True,
    )


@task
def build_agent(context: Context) -> None:
    """Build the agent dependency"""
    print_header("Building the agent dependency...")
    with context.cd("helm/agent"):
        context.run("helm dependency update", pty=True)


@task
def install(context: Context) -> None:
    """Install the agent."""
    print_header("Installing the agent Helm chart...")
    context.run(f"helm install agent helm/agent -n {KUBERNETES_ROOT_NAMESPACE} --create-namespace", pty=True)


@task(pre=[build_image, build_agent, install])
def start(context: Context) -> None:
    """Start the agent."""


@task(pre=[start])
def restart(context: Context) -> None:
    """Restart the agent."""
