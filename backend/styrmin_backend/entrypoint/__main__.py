"""Allow running as: python -m styrmin_backend.entrypoint.combined

Delegates to the styrmin CLI agent command.
"""

from styrmin_backend.cli.agent import agent_app

agent_app()
