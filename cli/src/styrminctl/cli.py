import sys

try:
    from .cli_commands import app
except ImportError as exc:
    sys.exit(f"Module {exc.name} is not available")

__all__ = ["app"]
