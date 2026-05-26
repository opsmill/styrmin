from dataclasses import dataclass

from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.driver.models.structure.source import DriverSource


@dataclass
class ApplicationDriver:
    source: DriverSource
    driver_spec: DriverSpec
    values_template: str
    # Spec 013 — Driver Reload Identity (Provenance Fingerprint).
    # Populated by ``DriverLoader.load_driver`` for local-sourced drivers
    # (SHA-256 over the three-file canonical concatenation). Git-sourced
    # drivers carry ``source_commit_sha`` instead; both nullable so the
    # legacy code paths and tests that don't compute it remain valid.
    content_hash: str | None = None
    source_commit_sha: str | None = None
