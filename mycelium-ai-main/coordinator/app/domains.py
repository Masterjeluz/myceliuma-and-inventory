"""Future-domain extension points (BIG #10, deel 10).

Registry only: named extension slots for Health, Skills and
universal ingestion so later work has somewhere explicit to
land. No health engine, no Garmin, no scrapers, no models —
only reserved capability namespaces, closed record shapes
(validated but never persisted here) and documentation
pointers. Anything beyond registration refuses.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

HEALTH = "health"
SKILLS = "skills"
INGESTION = "ingestion"

REGISTERED_DOMAINS = frozenset({HEALTH, SKILLS, INGESTION})

DOMAIN_STATUS = "planned"

#: Reserved capability namespaces per domain. Reserved means
#: documented-for-later: nothing grants or checks them yet.
DOMAIN_CAPABILITIES = {
    HEALTH: ("health.read", "health.log"),
    SKILLS: ("skills.read", "skills.track"),
    INGESTION: ("ingest.propose",),
}

#: Universal ingestion pattern stages (deel 10): source →
#: extract → understand → propose → approve → store. Stage
#: names only; the pipeline itself is future work.
INGESTION_STAGES = ("source", "extract", "understand", "propose",
                    "approve", "store")


class DomainRefusedError(ValueError):
    """Anything beyond registration refuses."""


class DomainInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=40)
    status: str = Field(default=DOMAIN_STATUS, max_length=20)
    capabilities: list[str] = Field(default_factory=list)
    docs: str = Field(default="", max_length=200)


def domain_info(domain: str) -> DomainInfo:
    """Describe one reserved domain. Unknown domains refuse."""
    if domain not in REGISTERED_DOMAINS:
        raise DomainRefusedError(
            f"Unknown domain '{domain}'; reserved: "
            f"{sorted(REGISTERED_DOMAINS)}")
    return DomainInfo(
        domain=domain, status=DOMAIN_STATUS,
        capabilities=list(DOMAIN_CAPABILITIES[domain]),
        docs=f"docs/future-domains.md#{domain}")


def list_domains() -> list[DomainInfo]:
    return [domain_info(domain)
            for domain in sorted(REGISTERED_DOMAINS)]


def ingestion_stage(stage: str) -> str:
    """Validate one universal-ingestion stage name."""
    if stage not in INGESTION_STAGES:
        raise DomainRefusedError(
            f"Unknown ingestion stage '{stage}'")
    return stage
