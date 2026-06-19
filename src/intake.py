"""
Intake structure for the Presence Health Check scanner.

Core fix for the "ranked among hotels" problem:
- Category is REQUIRED and comes from a controlled taxonomy (not free text, not AI-guessed)
- This category anchors every downstream AI prompt and competitor lookup
"""

import re
from dataclasses import dataclass, field
from typing import Optional


def _pluralize(phrase: str) -> str:
    """Basic English pluralization for category/positioning phrases used in
    AI prompts (e.g. "marketing agency" -> "marketing agencies",
    "home services contractor" -> "home services contractors").

    Only handles the common cases that appear in our taxonomy phrases:
    words ending in 'y' preceded by a consonant -> 'ies'; otherwise add 's'.
    Not a general-purpose pluralizer, but sufficient for short category
    phrases like those in CATEGORY_TAXONOMY.
    """
    phrase = phrase.strip()
    if not phrase:
        return phrase
    if phrase.endswith("y") and len(phrase) > 1 and phrase[-2] not in "aeiou":
        return phrase[:-1] + "ies"
    if phrase.endswith(("s", "x", "z", "ch", "sh")):
        return phrase + "es"
    return phrase + "s"


# Simplified controlled taxonomy (subset of common SMB/B2B categories).
# This is intentionally small for MVP - expand as needed.
# Each category includes example "search phrasing" used to anchor AI prompts.
CATEGORY_TAXONOMY = {
    "professional_services": {
        "label": "Professional Services (Law, Accounting, Consulting)",
        "ai_phrase": "professional services firm"
    },
    "marketing_agency": {
        "label": "Marketing / Digital Agency",
        "ai_phrase": "marketing agency"
    },
    "healthcare_medtech": {
        "label": "Healthcare / Medical / Medtech",
        "ai_phrase": "healthcare provider or medical business"
    },
    "saas_software": {
        "label": "SaaS / Software Company",
        "ai_phrase": "software company"
    },
    "hospitality_lodging": {
        "label": "Hospitality / Lodging (Hotels, B&Bs)",
        "ai_phrase": "hotel or lodging business"
    },
    "restaurant_food": {
        "label": "Restaurant / Food Service",
        "ai_phrase": "restaurant"
    },
    "retail_ecommerce": {
        "label": "Retail / E-commerce",
        "ai_phrase": "retail or online store"
    },
    "home_services": {
        "label": "Home Services (Plumbing, HVAC, Contracting)",
        "ai_phrase": "home services contractor"
    },
    "signage_printing": {
        "label": "Signage / Printing / Commercial Fabrication",
        "ai_phrase": "commercial sign company"
    },
    "automotive": {
        "label": "Automotive (Repair, Dealership, Detailing)",
        "ai_phrase": "automotive business"
    },
    "legal_financial": {
        "label": "Legal / Financial Services",
        "ai_phrase": "legal or financial services firm"
    },
    "real_estate": {
        "label": "Real Estate",
        "ai_phrase": "real estate business"
    },
    "fitness_wellness": {
        "label": "Fitness / Wellness / Personal Care",
        "ai_phrase": "fitness or wellness business"
    },
    "education_training": {
        "label": "Education / Training / Coaching",
        "ai_phrase": "education or coaching business"
    },
    "other": {
        "label": "Other (manual review required)",
        "ai_phrase": None  # flag for human review if selected
    },
}


@dataclass
class BusinessIntake:
    business_name: str
    category_key: str          # must be a key in CATEGORY_TAXONOMY - drives competitor/AI-recommendation prompts
    city: str
    region: Optional[str] = None   # state/province
    domain: str = ""
    known_competitors: list[str] = field(default_factory=list)  # user-supplied, beats AI-guessed
    positioning_phrase: str = ""   # how the business describes itself (e.g. "AI Visibility Strategy")
                                     # used for title/content clarity checks instead of the broad category
    custom_category_phrase: str = ""  # override for ai_phrase when no taxonomy category fits well
                                        # (e.g. "sign company" when forced to pick "home_services").
                                        # Takes precedence over the taxonomy's ai_phrase for AI prompts.

    def __post_init__(self):
        if self.category_key not in CATEGORY_TAXONOMY:
            raise ValueError(
                f"Invalid category '{self.category_key}'. "
                f"Must be one of: {list(CATEGORY_TAXONOMY.keys())}"
            )

    @property
    def category_label(self) -> str:
        return CATEGORY_TAXONOMY[self.category_key]["label"]

    @property
    def ai_phrase(self) -> Optional[str]:
        """Phrase used to anchor AI prompts to the correct industry/competitor search.

        Uses custom_category_phrase if supplied (for businesses that don't fit
        neatly into the taxonomy - e.g. a sign company forced into "home_services").
        Falls back to the taxonomy's broad category phrase otherwise.
        """
        return self.custom_category_phrase.strip() or CATEGORY_TAXONOMY[self.category_key]["ai_phrase"]

    @property
    def ai_phrase_plural(self) -> Optional[str]:
        """Pluralized form of ai_phrase, for prompts like "well-known X agencies"."""
        phrase = self.ai_phrase
        return _pluralize(phrase) if phrase else phrase

    @property
    def clarity_check_phrase(self) -> Optional[str]:
        """Phrase used to check title/content clarity.

        Prefers the business's own positioning phrase (how they describe
        themselves) since that's what they're trying to be found for.
        Falls back to the broad category phrase if none supplied.
        """
        return self.positioning_phrase.strip() or self.ai_phrase

    @property
    def location_str(self) -> str:
        if self.region:
            return f"{self.city}, {self.region}"
        return self.city

    @property
    def is_remote(self) -> bool:
        """True if the business has no meaningful physical location for
        local-search purposes (e.g. city is "Remote", "Worldwide", "N/A").

        This matters because AI prompts like "I'm looking for a X in
        {location}" produce nonsensical results for "X in Remote" - the
        recommendation/competitor prompts need different phrasing for
        these businesses.
        """
        remote_markers = {"remote", "worldwide", "online", "n/a", "global", "anywhere", "virtual"}
        city_lower = self.city.strip().lower()
        # Check if city is composed entirely of remote-indicating words
        # (handles "Remote", "Remote / Worldwide", "Remote/Online", etc.)
        tokens = re.split(r"[\s/,]+", city_lower)
        tokens = [t for t in tokens if t]
        return bool(tokens) and all(t in remote_markers for t in tokens)

    @property
    def location_phrase_for_ai(self) -> str:
        """Location phrase suitable for AI prompts.

        For businesses with a real city, returns "in {location_str}".
        For remote/distributed businesses, returns "" (empty) so prompts
        can be phrased without a location clause at all (e.g. "well-known
        providers of X" instead of "X in Remote").
        """
        if self.is_remote:
            return ""
        return f"in {self.location_str}"

    @property
    def recommendation_question_display(self) -> str:
        """Human-readable version of the recommendation prompt actually sent
        to AI, for display in reports. Mirrors the phrasing logic in
        ai_visibility.py's prompt 2 so reports accurately reflect what was asked.
        """
        if self.is_remote:
            return f"Can you recommend some well-known {self.ai_phrase_plural}?"
        return (
            f"I'm looking for a {self.ai_phrase} in {self.location_str}, "
            f"can you recommend a few options?"
        )

    @property
    def needs_manual_review(self) -> bool:
        return self.category_key == "other"


if __name__ == "__main__":
    # Quick sanity test using Elizabeth Koehler's business as a test case
    test = BusinessIntake(
        business_name="Elizabeth Koehler",
        category_key="marketing_agency",
        city="Remote",
        domain="elizabethkoehler.com",
        known_competitors=["Profound", "Scrunch", "Otterly.ai"]
    )
    print(f"Business: {test.business_name}")
    print(f"Category: {test.category_label}")
    print(f"AI anchor phrase: {test.ai_phrase}")
    print(f"Location: {test.location_str}")
    print(f"Needs manual review: {test.needs_manual_review}")
