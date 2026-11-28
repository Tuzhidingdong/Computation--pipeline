"""Contracts and local-only configuration for native literature acquisition.

Directly migrated capability family from Tuzhidingdong/chem-literature
commit e099406adb689281c0337bcacc7868c3ccdbc438.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SOURCE_REPOSITORY = "https://github.com/Tuzhidingdong/chem-literature"
SOURCE_COMMIT = "e099406adb689281c0337bcacc7868c3ccdbc438"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def doi_storage_id(doi: str) -> str:
    """Collision-resistant, filesystem-safe DOI key; never use sanitization alone."""
    original = str(doi or "").strip().casefold()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._-")[:64] or "unknown-doi"
    return f"{slug}-{hashlib.sha256(original.encode('utf-8')).hexdigest()[:12]}"


def resolve_config_path(value: str | Path | None, *, base_dir: str | Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    expanded = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return (expanded if expanded.is_absolute() else Path(base_dir) / expanded).resolve()


class AcquisitionStatus(str, Enum):
    FULL_TEXT_PLUS_SI = "FULL_TEXT_PLUS_SI"
    FULL_TEXT_ONLY = "FULL_TEXT_ONLY"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class ArtifactRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PARTIAL = "PARTIAL"
    LOCAL_UNREGISTERED = "LOCAL_UNREGISTERED"
    NOT_REQUESTED = "NOT_REQUESTED"


@dataclass(frozen=True)
class LiteratureTarget:
    doi: str
    title: str
    year: int | None = None
    source_urls: tuple[str, ...] = ()
    publisher_hint: str | None = None
    record_id: str | None = None
    requires_si: bool = False
    si_requirement_basis: str = "SI_NOT_REQUIRED_BY_RESEARCH_PLAN"

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, requires_si: bool = False,
                    si_requirement_basis: str | None = None) -> "LiteratureTarget":
        urls = []
        for item in record.get("source_records", []) or []:
            if isinstance(item, Mapping) and item.get("source_url"):
                urls.append(str(item["source_url"]))
        for item in record.get("source_urls", []) or []:
            if item:
                urls.append(str(item))
        year = record.get("year") or record.get("publication_year")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None
        return cls(
            doi=str(record.get("doi") or "").strip(),
            title=str(record.get("title") or "").strip(),
            year=year,
            source_urls=tuple(dict.fromkeys(urls)),
            publisher_hint=str(record.get("publisher") or record.get("publisher_name") or "") or None,
            record_id=str(record.get("record_id") or "") or None,
            requires_si=bool(requires_si),
            si_requirement_basis=si_requirement_basis or (
                "RESEARCH_PLAN_REQUIRES_SI" if requires_si else "SI_NOT_REQUIRED_BY_RESEARCH_PLAN"
            ),
        )


@dataclass(frozen=True)
class AcquisitionConfig:
    enabled: bool = False
    output_dir: str = "literature_acquisition"
    cookie_dir: str = "webvpn-cookies"
    portal_url: str | None = None
    publisher_resource_ids: Mapping[str, int] = field(default_factory=dict)
    browser_executable: str | None = None
    browser_headless: bool = True
    max_workers: int = 1
    min_delay_seconds: float = 16.0
    max_delay_seconds: float = 28.0
    max_consecutive_failures: int = 3
    cooldown_seconds: float = 120.0
    max_full_text_candidates: int = 20
    si_policy: str = "auto"
    preprocessing_enabled: bool = True
    grobid_enabled: bool = False
    grobid_url: str = "http://localhost:8070"
    grobid_timeout_seconds: int = 30
    max_zip_member_bytes: int = 100 * 1024 * 1024
    max_zip_total_bytes: int = 512 * 1024 * 1024
    max_zip_members: int = 250
    max_download_bytes: int = 250 * 1024 * 1024
    browser_start_timeout_seconds: int = 20
    cdp_timeout_seconds: int = 30
    artifact_format_ids: Mapping[str, str] = field(default_factory=dict)
    cookie_base_dir: str | None = None
    config_path: str | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None, *, base_dir: str | Path) -> "AcquisitionConfig":
        raw = dict(values or {})
        base = Path(base_dir).expanduser().resolve()
        allowed = {item.name for item in cls.__dataclass_fields__.values()}
        raw = {key: value for key, value in raw.items() if key in allowed}
        path_keys = ("output_dir", "cookie_dir", "browser_executable")
        for key in path_keys:
            value = raw.get(key)
            if value:
                raw[key] = str(resolve_config_path(value, base_dir=base))
        if not raw.get("output_dir"):
            raw["output_dir"] = str((base / "literature_acquisition").resolve())
        if not raw.get("cookie_dir"):
            raw["cookie_dir"] = str((base / ".pipeline" / "webvpn-cookies").resolve())
        if raw.get("browser_executable"):
            raw["browser_executable"] = str(Path(raw["browser_executable"]).resolve())
        raw["cookie_base_dir"] = str(base)
        cfg = cls(**raw)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.max_workers < 1 or self.max_full_text_candidates < 1:
            raise ValueError("max_workers and max_full_text_candidates must be >= 1")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")
        if self.min_delay_seconds < 0 or self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("invalid bounded request delay range")
        if self.cooldown_seconds < 0 or self.grobid_timeout_seconds < 1:
            raise ValueError("cooldown must be non-negative and GROBID timeout positive")
        if self.max_zip_member_bytes < 1 or self.max_zip_total_bytes < self.max_zip_member_bytes:
            raise ValueError("invalid SI ZIP extraction limits")
        if self.max_zip_members < 1 or self.max_download_bytes < 1024:
            raise ValueError("invalid acquisition size/count limits")
        if self.si_policy not in {"auto", "required", "optional", "disabled"}:
            raise ValueError("si_policy must be auto, required, optional, or disabled")
        for key, value in self.publisher_resource_ids.items():
            if not str(key).strip() or int(value) <= 0:
                raise ValueError("publisher_resource_ids must contain positive integer resource IDs")

    def with_overrides(self, **overrides: Any) -> "AcquisitionConfig":
        payload = asdict(self)
        payload.update({key: value for key, value in overrides.items() if value is not None})
        result = AcquisitionConfig(**payload)
        result.validate()
        return result

    def report_settings(self) -> dict[str, Any]:
        """Public, non-secret configuration snapshot; never contains cookie contents or filenames."""
        return {
            "enabled": self.enabled,
            "output_dir": self.output_dir,
            "portal_configured": bool(self.portal_url),
            "publisher_resource_ids": {str(k): int(v) for k, v in self.publisher_resource_ids.items()},
            "browser_executable_configured": bool(self.browser_executable),
            "browser_headless": self.browser_headless,
            "max_workers": self.max_workers,
            "delay_seconds": {"min": self.min_delay_seconds, "max": self.max_delay_seconds},
            "max_consecutive_failures": self.max_consecutive_failures,
            "cooldown_seconds": self.cooldown_seconds,
            "max_full_text_candidates": self.max_full_text_candidates,
            "si_policy": self.si_policy,
            "preprocessing_enabled": self.preprocessing_enabled,
            "grobid_enabled": self.grobid_enabled,
            "grobid_url_configured": bool(self.grobid_url),
            "max_zip_member_bytes": self.max_zip_member_bytes,
            "max_zip_total_bytes": self.max_zip_total_bytes,
            "max_zip_members": self.max_zip_members,
            "max_download_bytes": self.max_download_bytes,
            "artifact_format_ids_configured": sorted(self.artifact_format_ids.keys()),
        }


def decide_si_requirement(config: AcquisitionConfig, *, context: Mapping[str, Any],
                          profile: Mapping[str, Any] | None = None) -> tuple[bool, str]:
    """SI is required only when configured or explicitly declared by the ResearchPlan/profile."""
    if config.si_policy == "disabled":
        return False, "SI_DISABLED_BY_CONFIGURATION"
    if config.si_policy == "required":
        return True, "SI_REQUIRED_BY_CONFIGURATION"
    if config.si_policy == "optional":
        return False, "SI_OPTIONAL_BY_CONFIGURATION"

    profile = dict(profile or {})
    planning = profile.get("scientific_planning") or profile.get("planning") or {}
    intent = planning.get("intent") or profile.get("intent") or {}
    explicit_keys = (
        planning.get("requires_supplementary_information"),
        intent.get("requires_supplementary_information"),
        profile.get("requires_supplementary_information"),
        context.get("requires_supplementary_information"),
    )
    for value in explicit_keys:
        if value is True:
            return True, "SI_EXPLICITLY_REQUIRED_BY_RESEARCH_PLAN"
        if value is False:
            return False, "SI_EXPLICITLY_NOT_REQUIRED_BY_RESEARCH_PLAN"
    question = " ".join(str(context.get(key) or "") for key in (
        "research_question", "research_goal", "target_conclusion", "observables"
    )).casefold()
    if re.search(r"\b(supporting information|supplementary information|\bsi\b|supplementary data)\b", question):
        return True, "SI_DEPENDENCY_INFERRED_FROM_EXPLICIT_RESEARCH_QUESTION"
    return False, "SI_NOT_REQUIRED_BY_RESEARCH_PLAN"


def load_local_acquisition_config(path: str | Path, *, base_dir: str | Path) -> AcquisitionConfig:
    """Read a user-owned local JSON config. Secrets stay in separate cookie files."""
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("literature acquisition config must be a JSON object")
    result = AcquisitionConfig.from_mapping(payload, base_dir=config_path.parent)
    object.__setattr__(result, "config_path", str(config_path))
    return result
