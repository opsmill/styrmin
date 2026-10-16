import re

from coolname import generate_slug

DEPLOYMENT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DEPLOYMENT_NAME_MAX_LENGTH = 63


def generate_instance_name() -> str:
    """Generate a random two-word instance name; another instance may already have it."""
    return generate_slug(2)


def validate_deployment_name(name: str) -> str:
    """Validate a deployment name.

    Rules:
    - Must match ^[a-z0-9][a-z0-9_-]*$
    - Length 1–63 characters

    Returns the validated name.
    Raises ValueError if the name is invalid.
    """
    if not name:
        raise ValueError("Deployment name must not be empty")
    if len(name) > DEPLOYMENT_NAME_MAX_LENGTH:
        raise ValueError(
            f"Deployment name must be at most {DEPLOYMENT_NAME_MAX_LENGTH} characters, got {len(name)}"
        )
    if not DEPLOYMENT_NAME_PATTERN.match(name):
        raise ValueError(
            f"Deployment name '{name}' is invalid. "
            "Must contain only lowercase letters, numbers, hyphens, and underscores, "
            "and must start with a letter or number."
        )
    return name


def generate_deployment_name(driver_name: str, existing_names: list[str]) -> str:
    """Generate a deployment name based on the driver name.

    Format: <driver_name>-<N> where N is the next sequential number.
    N is determined by finding the highest existing number and incrementing by one.

    Args:
        driver_name: The application driver name.
        existing_names: List of existing deployment names to check for numbering.

    Returns:
        A generated deployment name like "infrahub-1", "infrahub-2", etc.
    """
    pattern = re.compile(rf"^{re.escape(driver_name)}-(\d+)$")
    max_number = 0
    for name in existing_names:
        match = pattern.match(name)
        if match:
            number = int(match.group(1))
            if number > max_number:
                max_number = number

    generated = f"{driver_name}-{max_number + 1}"

    # Handle edge case where generated name exceeds max length
    if len(generated) > DEPLOYMENT_NAME_MAX_LENGTH:
        # Truncate driver name to fit within limit
        suffix = f"-{max_number + 1}"
        max_prefix_len = DEPLOYMENT_NAME_MAX_LENGTH - len(suffix)
        generated = f"{driver_name[:max_prefix_len]}{suffix}"

    return generated
