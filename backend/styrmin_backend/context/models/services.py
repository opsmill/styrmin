"""Service reference context model for Jinja2 template rendering.

Provides a read-only view of a deployed service, injected into the template
context so consuming applications can reference services via
``{{ services.<name>.url }}``, ``{{ services.<name>.host }}``, etc.
"""

from pydantic import BaseModel, ConfigDict, computed_field


class ServiceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int
    kind: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        if self.kind in ("http", "https"):
            return f"{self.kind}://{self.host}:{self.port}"
        return f"{self.host}:{self.port}"
