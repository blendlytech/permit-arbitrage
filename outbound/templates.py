"""
Email Templates for Outbound Sales (Phase 4) — v2

Tone: Established permit-data service expanding into a new market.
Positions the sender as experienced, not brand-new.
Includes a link to the professional landing page for credibility.
"""


def render_subject_a(permit_count: int, niche: str, county: str) -> str:
    """Standard pitch — established service opening a new market."""
    return f"{permit_count} fresh {niche.lower()} permits in {county} this week - one slot open"


def render_subject_b(permit_count: int, county: str) -> str:
    """Small-city angle — exclusivity + local focus."""
    return f"We just expanded permit tracking to {county} - {permit_count} leads this week"


def render_body_a(
    first_name: str,
    permit_count: int,
    niche: str,
    county: str,
    sender_name: str = "James",
    landing_url: str = "https://www.rareplantvendors.com/permits",
) -> str:
    """Template A — Standard pitch for established markets."""
    return (
        f"Hi {first_name},\n\n"
        f"We run a permit-data service for contractors. After a highly successful year delivering "
        f"exclusive leads across Florida, we're expanding our pipeline to brand new territories.\n\n"
        f"We just opened up coverage in {county} and picked up {permit_count} "
        f"fresh {niche.lower()} permits this week alone (these are homeowner-filed, meaning they "
        f"are looking for a contractor).\n\n"
        f"We limit each county to one contractor per trade to keep the leads exclusive. "
        f"I wanted to reach out before we fill the {county} slot.\n\n"
        f"Mind if I send over our site so you can see how it works? I can also shoot you "
        f"this week's list for free so you can check the data quality.\n\n"
        f"Best,\n{sender_name}\n"
        f"PermitLeads Data"
    )


def render_body_b(
    first_name: str,
    permit_count: int,
    county: str,
    sender_name: str = "James",
    landing_url: str = "https://www.rareplantvendors.com/permits",
) -> str:
    """Template B — Small-city angle, emphasizing local exclusivity."""
    return (
        f"Hi {first_name},\n\n"
        f"We provide exclusive permit lead lists to contractors. Due to high demand "
        f"over the past year, we're rapidly expanding our data pipelines to new territories.\n\n"
        f"We just opened up coverage for {county} and already have {permit_count} "
        f"active permits on file for this week. We limit each county to one contractor per "
        f"trade so nobody's competing on the same leads.\n\n"
        f"I'm reaching out to see if you'd want the {county} slot before we offer "
        f"it elsewhere.\n\n"
        f"Would you be opposed to me sending over our site with pricing details? "
        f"I can also send you this week's {county} list completely free so you can see what you'd be getting.\n\n"
        f"Best,\n{sender_name}\n"
        f"PermitLeads Data"
    )


def render_followup(
    first_name: str,
    sender_name: str = "James",
    landing_url: str = "https://www.rareplantvendors.com/permits",
) -> tuple:
    """Returns (subject, body) for the 48-hour follow-up."""
    subject = "Quick follow-up on the permit list"
    body = (
        f"Hi {first_name},\n\n"
        f"Just circling back on this. We added 3 more permits to the {first_name} "
        f"area list since my last email.\n\n"
        f"Happy to send a sample batch - just say the word.\n\n"
        f"Best,\n{sender_name}\n"
    )
    return subject, body
