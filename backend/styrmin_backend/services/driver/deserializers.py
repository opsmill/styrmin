"""Re-export of ``styrmin_sdk.driver_format.reading.deserializers``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.reading.deserializers import (
    Deserializer,
    DriverSpecDeserializer,
    ModelType,
    _field_path,
    format_validation_error,
    get_deserializer,
)

__all__ = [
    "Deserializer",
    "DriverSpecDeserializer",
    "ModelType",
    "format_validation_error",
    "get_deserializer",
    "_field_path",
]
