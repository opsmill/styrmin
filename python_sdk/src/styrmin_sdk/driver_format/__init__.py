"""Driver format code that the Styrmin server, the agent and ``styrmin-driver`` share.

The package reads, checks and renders an application driver directory, and holds the
context model that a driver's values template reads. The backend imports it, so the load,
the render and the command apply one set of rules. See ADR-0089.
"""
