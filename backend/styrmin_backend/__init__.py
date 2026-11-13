# import importlib.metadata
import os

# Loguru's ``diagnose`` prints the value of each variable of a traceback, such as
# an action token, so it is off in every Styrmin process unless an operator turns
# it on. Loguru reads the variable when it is first imported, so this runs first.
os.environ.setdefault("LOGURU_DIAGNOSE", "NO")

from styrmin_backend.redaction import install_log_redaction  # noqa: E402

# Every process that runs Styrmin code imports this package first: the server,
# the agent, and the flow runs of the task worker, the agent and driver actions.
install_log_redaction()

__version__ = "0.1.0"
# __version__ = importlib.metadata.version("styrmin-backend")
