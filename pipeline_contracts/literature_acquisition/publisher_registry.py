"""Explicit publisher routes migrated from chem-literature's supported methods.

Only Elsevier, Wiley, and IOP/ECS have real authenticated full-text routines.
Other publishers are explicitly NOT_IMPLEMENTED and are never inferred as supported.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class PublisherDefinition:
    key: str
    label: str
    resource_key: str
    supported: bool
    method: str
    domains: tuple[str, ...]
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SUPPORTED_PUBLISHERS = {
    "elsevier": PublisherDefinition(
        key="elsevier", label="Elsevier / ScienceDirect", resource_key="elsevier",
        supported=True, method="crossref_pii_cdp_render_print_pdf",
        domains=("sciencedirect.com", "elsevier.com", "ars.els-cdn.com"),
        note="Crossref DOI→PII, ScienceDirect DOM lazy-load/print CSS cleanup, CDP Page.printToPDF, MMC/SI discovery.",
    ),
    "wiley": PublisherDefinition(
        key="wiley", label="Wiley Online Library", resource_key="wiley",
        supported=True, method="pdfdirect_and_downloadSupplement",
        domains=("onlinelibrary.wiley.com", "wiley.com"),
        note="Authenticated /doi/pdfdirect/{doi}?download=true and downloadSupplement link discovery.",
    ),
    "iop_ecs": PublisherDefinition(
        key="iop_ecs", label="IOP Publishing / ECS", resource_key="iop_ecs",
        supported=True, method="article_doi_pdf_endpoint",
        domains=("iopscience.iop.org", "publishings.iop.org", "ecsdl.org"),
        note="Authenticated /article/{doi}/pdf binary endpoint.",
    ),
}

NOT_IMPLEMENTED_PUBLISHERS = {
    "springer": ("springer.com", "link.springer.com"),
    "acs": ("acs.org", "pubs.acs.org"),
    "rsc": ("rsc.org", "pubs.rsc.org"),
    "nature": ("nature.com",),
    "science": ("science.org", "sciencemag.org"),
}
NOT_IMPLEMENTED_PUBLISHER_ALIASES = {
    "springer": ("springer", "springer nature"),
    "acs": ("acs", "american chemical society"),
    "rsc": ("rsc", "royal society of chemistry"),
    "nature": ("nature portfolio",),
    "science": ("science", "american association for the advancement of science", "aaas"),
}

def _matches(host: str, domain: str) -> bool:
    host = host.casefold().split(":", 1)[0]
    domain = domain.casefold()
    return host == domain or host.endswith("." + domain)


def detect_publisher(record: Mapping[str, Any]) -> PublisherDefinition | None:
    candidates = []
    for value in record.get("source_urls", []) or []:
        candidates.append(str(value))
    publisher_values = []
    for source in record.get("source_records", []) or []:
        if isinstance(source, Mapping):
            if source.get("source_url"):
                candidates.append(str(source["source_url"]))
            if source.get("publisher"):
                publisher_values.append(str(source["publisher"]))
    for value in (record.get("publisher"), record.get("publisher_name")):
        if value:
            publisher_values.append(str(value))
    for value in (record.get("url"), record.get("landing_page_url"), record.get("publisher_url")):
        if value:
            candidates.append(str(value))
    for raw_url in candidates:
        try:
            host = urlparse(raw_url).hostname or ""
        except ValueError:
            continue
        for definition in SUPPORTED_PUBLISHERS.values():
            if any(_matches(host, domain) for domain in definition.domains):
                return definition
        for key, domains in NOT_IMPLEMENTED_PUBLISHERS.items():
            if any(_matches(host, domain) for domain in domains):
                return PublisherDefinition(
                    key=key, label=key.upper(), resource_key=key, supported=False,
                    method="NOT_IMPLEMENTED", domains=tuple(domains),
                    note=f"{key} has no validated downloader in this Pipeline port.",
                )

    hint = " ".join(
        publisher_values + [
            str(record.get("publisher") or ""),
            str(record.get("publisher_name") or ""),
        ]
    ).casefold()
    for definition in SUPPORTED_PUBLISHERS.values():
        if any(token in hint for token in {
            "elsevier": ("elsevier", "science direct"),
            "wiley": ("wiley",),
            "iop_ecs": ("iop", "electrochemical society", "ecs"),
        }[definition.key]):
            return definition
    for key, domains in NOT_IMPLEMENTED_PUBLISHERS.items():
        if any(alias in hint for alias in NOT_IMPLEMENTED_PUBLISHER_ALIASES[key]):
            return PublisherDefinition(
                key=key, label=key.upper(), resource_key=key, supported=False,
                method="NOT_IMPLEMENTED", domains=tuple(domains),
                note=f"{key} has no validated downloader in this Pipeline port.",
            )
    return None


def publisher_support_matrix() -> list[dict[str, Any]]:
    rows = [item.as_dict() for item in SUPPORTED_PUBLISHERS.values()]
    rows.extend({
        "key": key, "label": key.upper(), "resource_key": key, "supported": False,
        "method": "NOT_IMPLEMENTED", "domains": list(domains),
        "note": f"{key} downloader is not implemented; no support is inferred from a WebVPN resource ID.",
    } for key, domains in NOT_IMPLEMENTED_PUBLISHERS.items())
    return rows
