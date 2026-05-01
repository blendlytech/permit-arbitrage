# Permit Arbitrage (PermitLeads) - Project Guidelines

## Project Overview
A $0-cost data arbitrage system that scrapes municipal building permits, filters for homeowner-pulled leads, and manages outreach via a premium Flask dashboard.

## Tech Stack
- **Backend**: Python 3.10+ (Playwright, Flask, asyncio)
- **Database**: SQLite (`output/seen_permits.db`)
- **Scraper Platforms**: Accela, Citizenserve, Click2Gov, SmartGov
- **UI**: Vanilla CSS/JS (Dark Mode / Premium Aesthetics)

## Key Commands
- `python daemon.py`: Start the real-time monitoring daemon (cycles through jurisdictions).
- `python -m scrapers.main`: Run a manual scrape for a specific jurisdiction.
- `python dashboard/app.py`: Start the management dashboard.
- `pip install -r requirements.txt`: Install dependencies.

## Core Rules
- **Homeowner First**: Always prioritize `homeowner_only=True` filtering in scrapers.
- **Deduplication**: Never export leads without checking the SQLite hash.
- **CSV Configuration**: Use `-Jurisdiction-BasesearchportalURL-Nicherecordtypes.csv` for all jurisdiction mappings.
- **No Secrets**: Use `.env` for `GMAIL_APP_PASSWORD` and other API keys.
- **UI Excellence**: Dashboard updates must follow the "Deep Forest Luxe" or premium dark mode aesthetic.

## Jurisdiction Mapping (CSV Columns)
1. `Jurisdiction`: Name of the city/county.
2. `BaseSearchPortalURL`: URL of the Accela/Citizenserve portal.
3. `NicheRecordTypes`: Comma-separated list of record types (e.g., `Roofing,Pool`).

## Scraper Strategy
- **Accela**: Navigate to Search -> Permits -> Record Type -> Date Range.
- **Citizenserve**: Navigate to Reports/Search -> Date Range.
- **Click2Gov**: Navigate to Search -> Keyword search (Pool, Roof).
