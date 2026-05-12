from invoke import Context, task
from rich.console import Console

from .utils import graphql, load_query, print_header

# Default credentials seeded by the helm/compose dev fixtures (see
# dev/local/demo-values.yaml + docker-compose.yml). admin/styrmin is the
# convention for local development only — production installs MUST set a
# real STYRMIN_ADMIN_PASSWORD via helm value or env var.
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "styrmin"  # noqa: S105


def _login(console: Console, api_url: str, username: str, password: str) -> str:
    """Authenticate against the bootstrap admin and return a bearer token."""
    print_header(f"Logging in as '{username}'...")
    result = graphql(
        api_url,
        load_query("login"),
        {"username": username, "password": password},
    )
    if result.get("errors"):
        error = result["errors"][0]
        raise RuntimeError(
            f"Login failed for '{username}': {error['message']}. "
            f"Check STYRMIN_ADMIN_PASSWORD on the server (helm value "
            f"styrmin.adminPassword or env var)."
        )
    token: str = result["data"]["login"]["token"]
    console.print(f"[green]✓[/green] Logged in as '{username}'")
    return token


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


def _error_code(result: dict) -> str:  # type: ignore[type-arg]
    return result["errors"][0].get("extensions", {}).get("code", "")


def _bootstrap_cluster(
    console: Console,
    api_url: str,
    fqdn_suffix: str,
    *,
    token: str,
    external_url_scheme: str | None = None,
    external_url_port: int | None = None,
) -> str:
    print_header("Creating cluster record...")
    config: dict = {
        "fqdn_suffix": fqdn_suffix,
        "ingress_class": "traefik",
        "runtime_class": "default",
        "standard_storage": {"storage_class": "local-path"},
    }
    if external_url_scheme is not None:
        config["external_url_scheme"] = external_url_scheme
    if external_url_port is not None:
        config["external_url_port"] = external_url_port
    result = graphql(
        api_url,
        load_query("create_cluster"),
        {"name": "local", "config": config},
        token=token,
    )
    if result.get("errors"):
        error = result["errors"][0]
        if _error_code(result) == "ALREADY_EXISTS":
            console.print(f"[yellow]⚠[/yellow] Cluster already exists: {error['message']}")
            raise SystemExit(
                "Cluster already exists — run 'uv run invoke dev.clean' to reset, or use Bruno to get the existing cluster ID."
            )
        raise RuntimeError(f"Failed to create cluster: {error['message']}")
    cluster_id: str = result["data"]["createCluster"]["id"]
    console.print(f"[green]✓[/green] Cluster created: {cluster_id}")
    return cluster_id


def _bootstrap_environment(console: Console, api_url: str, cluster_id: str, token: str) -> str | None:
    print_header("Creating environment record...")
    result = graphql(
        api_url,
        load_query("create_environment"),
        {"name": "local", "clusterId": cluster_id, "config": {}},
        token=token,
    )
    if result.get("errors"):
        error = result["errors"][0]
        if _error_code(result) == "ALREADY_EXISTS":
            console.print(f"[yellow]⚠[/yellow] Environment already exists: {error['message']}")
            return None
        raise RuntimeError(f"Failed to create environment: {error['message']}")
    environment_id: str = result["data"]["createEnvironment"]["id"]
    console.print(f"[green]✓[/green] Environment created: {environment_id}")
    return environment_id


def _bootstrap_backup_storage(console: Console, api_url: str, environment_id: str | None, token: str) -> None:
    # Create a backup storage location pointing at the in-cluster MinIO and
    # assign it to the environment. Mirrors the e2e bootstrap flow.
    print_header("Creating backup storage location (MinIO)...")
    result = graphql(
        api_url,
        load_query("create_backup_storage_location"),
        {
            "name": "local",
            "endpoint": "http://minio.styrmin.svc:9000",
            "bucket": "velero",
            "region": "minio",
            "accessKeyId": "minioadmin",
            "secretAccessKey": "minioadmin",
        },
        token=token,
    )
    if result.get("errors"):
        error = result["errors"][0]
        if _error_code(result) != "ALREADY_EXISTS":
            raise RuntimeError(f"Failed to create backup storage location: {error['message']}")
        console.print(f"[yellow]⚠[/yellow] Backup storage location already exists: {error['message']}")
        return
    bsl_id: str = result["data"]["createBackupStorageLocation"]["id"]
    console.print(f"[green]✓[/green] Backup storage location created: {bsl_id}")

    if environment_id is None:
        return
    print_header("Assigning backup storage location to environment...")
    result = graphql(
        api_url,
        load_query("assign_backup_storage_location"),
        {"environmentId": environment_id, "backupStorageLocationId": bsl_id},
        token=token,
    )
    if result.get("errors"):
        raise RuntimeError(f"Failed to assign backup storage location: {result['errors'][0]['message']}")
    console.print("[green]✓[/green] Backup storage location assigned")


BUNDLED_DRIVERS: tuple[str, ...] = ("infrahub", "semaphore")


def _bootstrap_driver_version(console: Console, api_url: str, name: str, token: str) -> None:
    print_header(f"Loading local driver version ({name})...")
    result = graphql(
        api_url,
        load_query("load_local_driver_version"),
        {"path": f"/styrmin/drivers/{name}"},
        token=token,
    )
    if result.get("errors"):
        raise RuntimeError(f"Failed to load driver version: {result['errors'][0]['message']}")
    adv = result["data"]["loadLocalApplicationDriverVersion"]
    console.print(f"[green]✓[/green] Driver version loaded: {adv['version']} (id: {adv['id']})")


@task
def bootstrap(  # noqa: PLR0917
    context: Context,  # noqa: ARG001
    api_url: str = "http://localhost:8000/graphql",
    fqdn_suffix: str = "styrmin.com",
    external_url_scheme: str | None = None,
    external_url_port: int | None = None,
    admin_username: str = DEFAULT_ADMIN_USERNAME,
    admin_password: str = DEFAULT_ADMIN_PASSWORD,
) -> None:
    """Bootstrap Styrmin entities: cluster, environment, BSL, and local driver version.

    Default-deny is on (ADR-024/025): every mutation in the bootstrap
    sequence requires an authenticated admin session, so this task first
    logs in as the seeded bootstrap admin (default ``admin/styrmin``,
    matching ``docker-compose.yml`` and ``dev/local/demo-values.yaml``)
    and threads the bearer token through every call.
    """
    console = Console()
    token = _login(console, api_url, admin_username, admin_password)
    cluster_id = _bootstrap_cluster(
        console,
        api_url,
        fqdn_suffix,
        token=token,
        external_url_scheme=external_url_scheme,
        external_url_port=external_url_port,
    )
    environment_id = _bootstrap_environment(console, api_url, cluster_id, token=token)
    _bootstrap_backup_storage(console, api_url, environment_id, token=token)
    for driver_name in BUNDLED_DRIVERS:
        _bootstrap_driver_version(console, api_url, driver_name, token=token)
    console.print(
        "\n[bold green]Bootstrap complete![/bold green]"
        " Deploy an application from the Styrmin UI or with"
        " [cyan]uv run styrminctl deployments create[/cyan]."
    )
