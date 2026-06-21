"""Persistent telemetry state.

``TelemetryStore`` mirrors ``styrminctl.auth.token_store.TokenStore``: it
persists ``{install_id, enabled}`` to a JSON file with atomic writes and strict
permissions, lazily generating a stable ``install_id``. Implemented in T005.
"""
