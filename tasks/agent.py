from invoke import Context, task

from .utils import KUBERNETES_ROOT_NAMESPACE, print_header


@task
def build_image(context: Context) -> None:
    """Build the agent Docker image."""
    print_header("Building the agent Docker image...")
    context.run("docker build -t styrmin -f docker/Dockerfile .", pty=True)


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
