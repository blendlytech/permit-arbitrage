"""
Configuration and constants for the Permit Arbitrage scraper system.
"""
import os
from datetime import datetime, timedelta

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JURISDICTION_CSV = os.path.join(
    PROJECT_ROOT,
    "-Jurisdiction-BasesearchportalURL-Nicherecordtypes.csv"
)
if not os.path.exists(JURISDICTION_CSV):
    JURISDICTION_CSV = os.path.join(
        PROJECT_ROOT, ".agent", "rollout_sequences",
        "-Jurisdiction-BasesearchportalURL-Nicherecordtypes.csv"
    )
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

# ── Defaults ───────────────────────────────────────────────────────────────────
DEFAULT_TIMEFRAME_DAYS = 7
DEFAULT_NICHE = "Pool & Reroof Contractors"

# ── Niche keywords (used for post-scrape text filtering on portals without
#    explicit record-type dropdowns, e.g. Click2Gov) ────────────────────────────
NICHE_KEYWORDS = [
    "pool", "spa", "swimming pool",
    "roof", "reroof", "re-roof", "roofing",
]

# ── Platform identifiers ──────────────────────────────────────────────────────
PLATFORM_ACCELA = "accela"
PLATFORM_CITIZENSERVE = "citizenserve"
PLATFORM_CLICK2GOV = "click2gov"
PLATFORM_SMARTGOV = "smartgov"

# ── Browser settings ──────────────────────────────────────────────────────────
HEADLESS = False          # Keep visible so operator can handle CAPTCHAs
SLOW_MO = 300             # ms between actions (avoid rate-limiting)
DEFAULT_TIMEOUT = 30_000  # ms to wait for elements
PAGE_LOAD_TIMEOUT = 60_000

SCHEMA_FIELDS = [
    "permit_type",
    "issue_date",
    "property_address",
    "owner_name",
    "owner_first_name",
    "owner_last_name",
    "job_valuation",
]


def date_range(days_back: int = DEFAULT_TIMEFRAME_DAYS):
    """Return (start_date, end_date) as MM/DD/YYYY strings."""
    end = datetime.now()
    start = end - timedelta(days=days_back)
    return start.strftime("%m/%d/%Y"), end.strftime("%m/%d/%Y")
