"""Outcome and error-category classification.

``categorize_error(exc)`` maps an exception (or ``None`` for success) to an
``(outcome, error_category)`` pair, keyed on exception type and reusing the
existing typed-error hierarchy. No new exception classes. Implemented in T013.
"""
