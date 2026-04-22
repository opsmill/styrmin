from invoke import Context, task
from rich.console import Console

from .utils import graphql, load_query, print_header


@task
def start(context: Context, background: bool = True) -> None:
    """Start the Docker Compose services."""
    print_header("Starting Prefect services...")
    context.run(f"docker compose up{' -d' if background else ''}", pty=True)


@task
def stop(context: Context) -> None:
    """Stop the Docker Compose services."""
    print_header("Stopping Prefect services...")
    context.run("docker compose down", pty=True)


@task
def clean(context: Context) -> None:
    """Clean the volumes."""
    print_header("Cleaning the volumes...")
    context.run("docker compose down -v", pty=True)


@task
def build(context: Context) -> None:
    """Build the Docker Compose images."""
    print_header("Building Docker images...")
    context.run("docker compose build", pty=True)


@task(pre=[stop, clean, start])
def restart(context: Context) -> None:
    """Restart the Docker Compose services."""


@task
def bootstrap(
    context: Context,  # noqa: ARG001
    api_url: str = "http://localhost:8000/graphql",
    fqdn_suffix: str = "styrmin.com",
) -> None:
    """Bootstrap Styrmin entities: cluster, environment, and local driver version."""
    console = Console()

    # 1. Create cluster
    print_header("Creating cluster record...")
    result = graphql(
        api_url,
        load_query("create_cluster"),
        {
            "name": "local",
            "config": {
                "fqdn_suffix": fqdn_suffix,
                "ingress_class": "traefik",
                "dedicated_ingress": {"implementation": "traefik", "type": "ingress", "service": {"type": "ClusterIP"}},
                "runtime_class": "default",
                "standard_storage": {"storage_class": "local-path"},
            },
        },
    )
    if result.get("errors"):
        error = result["errors"][0]
        code = error.get("extensions", {}).get("code", "")
        if code == "ALREADY_EXISTS":
            console.print(f"[yellow]⚠[/yellow] Cluster already exists: {error['message']}")
            raise SystemExit(
                "Cluster already exists — run 'uv run invoke dev.clean' to reset, or use Bruno to get the existing cluster ID."
            )
        raise RuntimeError(f"Failed to create cluster: {error['message']}")
    cluster_id = result["data"]["createCluster"]["id"]
    console.print(f"[green]✓[/green] Cluster created: {cluster_id}")

    # 2. Create environment
    print_header("Creating environment record...")
    result = graphql(
        api_url,
        load_query("create_environment"),
        {
            "name": "local",
            "clusterId": cluster_id,
            "config": {"ip_whitelist": ["127.0.0.1"]},
        },
    )
    if result.get("errors"):
        error = result["errors"][0]
        code = error.get("extensions", {}).get("code", "")
        if code == "ALREADY_EXISTS":
            console.print(f"[yellow]⚠[/yellow] Environment already exists: {error['message']}")
        else:
            raise RuntimeError(f"Failed to create environment: {error['message']}")
    else:
        environment_id = result["data"]["createEnvironment"]["id"]
        console.print(f"[green]✓[/green] Environment created: {environment_id}")

    # 3. Load local driver version (auto-creates the ApplicationDriver if needed)
    print_header("Loading local driver version (infrahub)...")
    result = graphql(
        api_url,
        load_query("load_local_driver_version"),
        {"path": "/styrmin/drivers/infrahub"},
    )
    if result.get("errors"):
        error = result["errors"][0]
        raise RuntimeError(f"Failed to load driver version: {error['message']}")
    adv = result["data"]["loadLocalApplicationDriverVersion"]
    console.print(f"[green]✓[/green] Driver version loaded: {adv['version']} (id: {adv['id']})")

    console.print(
        "\n[bold green]Bootstrap complete![/bold green] You can now deploy Infrahub using Bruno (Deploy Infrahub, seq 8)."
    )
