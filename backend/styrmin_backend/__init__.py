# import importlib.metadata

from styrmin_backend.logging_bridge import install_sdk_log_forwarding

__version__ = "0.1.0"
# __version__ = importlib.metadata.version("styrmin-backend")

install_sdk_log_forwarding()
