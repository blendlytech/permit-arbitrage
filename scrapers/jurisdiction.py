"""
Jurisdiction CSV loader — reads the master jurisdiction list, cleans URLs,
and detects portal platforms.
"""
import csv
import re
from dataclasses import dataclass
from typing import List, Optional

from scrapers.config import (
    JURISDICTION_CSV,
    PLATFORM_ACCELA,
    PLATFORM_CITIZENSERVE,
    PLATFORM_CLICK2GOV,
    PLATFORM_SMARTGOV,
)


@dataclass
class Jurisdiction:
    """A single jurisdiction from the master CSV."""
    id: int
    name: str
    raw_url: str
    portal_url: str          # cleaned URL
    platform: str            # accela | citizenserve | click2gov | smartgov
    niche_record_types: str  # raw string from CSV column 4
    key_scraper_fields: str  # raw string from CSV column 5


# ── URL cleaning ──────────────────────────────────────────────────────────────

# Known garbage suffixes appended by the citation tool that generated the CSV.
_SUFFIX_PATTERNS = [
    r"aca-prod\.accela(?:\+\d+)?$",
    r"access\.okc$",
    r"civicplus$",
    r"citizenserve$",
    r"semc-egov\.aspgov$",
    r"lkwo-egov\.aspgov$",
    r"jurupavalley$",
    r"stancounty$",
    r"cityoflancasterca(?:\+\d+)?$",
    r"co-coconino-az\.smartgovcommunity$",
    r"mymanatee$",
    r"martin$",
    r"youtubelkwo-egov\.aspgov$",
    r"youtube(?:lkwo-egov\.aspgov)?$",
]


def _clean_url(raw: str) -> str:
    """
    Strip citation-tool garbage from the end of a URL.
    Also strip any leading text before 'https://'.
    """
    # Some rows have prefix text like "Accela Online Services: https://..."
    match = re.search(r"(https?://\S+)", raw)
    if match:
        url = match.group(1)
    else:
        url = raw.strip()

    # Strip navigation instructions like " → Building or Permits search"
    url = re.split(r"\s*→\s*", url)[0].strip()

    # Strip known garbage suffixes
    for pat in _SUFFIX_PATTERNS:
        url = re.sub(pat, "", url)

    # Generic fallback: strip anything after .aspx/.html/.com that isn't
    # a query string or path
    url = re.sub(r"(\.aspx|\.html)((?:\?[^#]*)?(?:#.*)?).*$",
                 r"\1\2", url)
    # For bare .com domains (SmartGov)
    url = re.sub(r"(\.com)(/[^?#]*)?((?:\?[^#]*)?(?:#.*)?).*$",
                 r"\1\2\3", url)

    return url.rstrip()


def _detect_platform(url: str, raw_url: str) -> str:
    """Detect the portal platform from the URL."""
    combined = (url + " " + raw_url).lower()
    if "citizenserve" in combined:
        return PLATFORM_CITIZENSERVE
    if "click2gov" in combined or "aspgov.com" in combined:
        return PLATFORM_CLICK2GOV
    if "smartgov" in combined:
        return PLATFORM_SMARTGOV
    # Default to Accela (most common)
    return PLATFORM_ACCELA


# ── CSV loading ───────────────────────────────────────────────────────────────

def load_jurisdictions(csv_path: str = JURISDICTION_CSV) -> List[Jurisdiction]:
    """Load and parse the jurisdiction master CSV."""
    jurisdictions: List[Jurisdiction] = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header row
        for row in reader:
            if len(row) < 5:
                continue
            raw_url = row[2].strip()
            portal_url = _clean_url(raw_url)
            platform = _detect_platform(portal_url, raw_url)
            jurisdictions.append(Jurisdiction(
                id=int(row[0]),
                name=row[1].strip(),
                raw_url=raw_url,
                portal_url=portal_url,
                platform=platform,
                niche_record_types=row[3].strip(),
                key_scraper_fields=row[4].strip(),
            ))
    return jurisdictions


def find_jurisdiction(name_fragment: str,
                      jurisdictions: Optional[List[Jurisdiction]] = None
                      ) -> Optional[Jurisdiction]:
    """Find a jurisdiction by partial name match (case-insensitive)."""
    if jurisdictions is None:
        jurisdictions = load_jurisdictions()
    fragment = name_fragment.lower()
    for j in jurisdictions:
        if fragment in j.name.lower():
            return j
    return None


def find_by_id(jid: int,
               jurisdictions: Optional[List[Jurisdiction]] = None
               ) -> Optional[Jurisdiction]:
    """Find a jurisdiction by its numeric ID."""
    if jurisdictions is None:
        jurisdictions = load_jurisdictions()
    for j in jurisdictions:
        if j.id == jid:
            return j
    return None
