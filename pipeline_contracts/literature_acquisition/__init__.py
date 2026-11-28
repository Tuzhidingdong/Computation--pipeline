"""Native literature acquisition package.

Heavy browser/PDF/DOCX dependencies are deliberately not imported here.
The existing metadata-only Scientific Research path must remain usable when
optional full-text acquisition dependencies are not installed.
"""
from .contracts import (
    AcquisitionConfig, AcquisitionStatus, ArtifactRegistrationStatus,
    LiteratureTarget, doi_storage_id,
)

__all__ = [
    "AcquisitionConfig", "AcquisitionStatus", "ArtifactRegistrationStatus",
    "LiteratureTarget", "doi_storage_id",
]
