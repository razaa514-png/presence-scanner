"""
AI Visibility (GEO) checker.

Queries an AI model with CATEGORY-ANCHORED prompts to determine:
1. Does the AI know this business exists?
2. When asked for recommendations in this category/location, is the business mentioned?
3. How does the AI describe the business (accuracy check)?
4. Who does the AI consider competitors (cross-checked against category)?

This avoids the "ranked among hotels" failure by NEVER asking generic
"who competes with X" - every prompt includes the declared category.
"""

import json
import os
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from intake import BusinessIntake


API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def _call_claude(prompt: str, max_tokens: int = 500) -> str:
    """Call Claude API with a single user prompt. Returns text response.

    Requires ANTHROPIC_API_KEY environment variable to be set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Set it before running the scanner."
        )

    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Concatenate all text blocks
            text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
            return "\n".join(text_parts)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        raise RuntimeError(f"API call failed [{e.code}]: {err_body}")
    except Exception as e:
        raise RuntimeError(f"API call failed: {str(e)}")


# Words/phrases that indicate a line is meta-commentary, not a business name.
# If a line contains any of these (case-insensitive), it's filtered out -
# even if the prompt asks for a clean list, models sometimes add
# self-corrections or caveats anyway.
_COMMENTARY_MARKERS = [
    "let me", "i should", "i need to", "correct", "actually", "wait,",
    "too far", "instead", "staying in", "however", "note:", "caveat",
    "i'm not", "i am not", "double-check", "verify", "disclaimer",
]


def _parse_competitor_list(raw_response: str) -> list:
    """Parse a competitor-name list from an AI response, filtering out
    meta-commentary/self-corrections that may leak through despite the
    prompt asking for a clean list.

    Heuristics:
    - Strip bullet/markdown formatting
    - Drop empty lines and lines starting with '[' (placeholder-style)
    - Drop lines containing commentary markers (case-insensitive)
    - Strip parenthetical asides like "(too far)" from otherwise-valid names
    - Drop lines that look like full sentences (end in '.'/':' and are long,
      or exceed a reasonable name length)
    - Deduplicate while preserving order (handles self-corrected lists that
      repeat earlier entries)
    """
    competitors = []
    seen = set()

    for line in raw_response.split("\n"):
        cleaned = line.strip("-•*: ").strip()
        if not cleaned or cleaned.startswith("["):
            continue

        lower = cleaned.lower()
        if any(marker in lower for marker in _COMMENTARY_MARKERS):
            continue

        # Strip trailing parenthetical asides, e.g. "Name (too far)" -> "Name"
        cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned).strip()
        if not cleaned:
            continue

        # Likely a sentence, not a name: ends in period/colon and is long
        if cleaned.endswith((".", ":")) and len(cleaned) > 40:
            continue

        # Unreasonably long for a business name - likely a sentence
        if len(cleaned) > 60:
            continue

        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        competitors.append(cleaned)

    return competitors


@dataclass
class AIVisibilityResult:
    knows_business: bool
    knowledge_summary: str
    appears_in_recommendations: bool
    recommendation_response: str
    competitors_mentioned: list
    category_mismatch_flag: bool
    niche_too_emerging: bool
    raw_responses: dict
    error: str = ""


def check_ai_visibility(intake: BusinessIntake) -> AIVisibilityResult:
    """Run category-anchored AI visibility checks for a business."""

    if intake.needs_manual_review:
        return AIVisibilityResult(
            knows_business=False,
            knowledge_summary="Category not specified - manual review required.",
            appears_in_recommendations=False,
            recommendation_response="",
            competitors_mentioned=[],
            category_mismatch_flag=True,
            niche_too_emerging=False,
            raw_responses={}
        )

    try:
        raw = {}

        # --- Prompt 1: Direct knowledge check ---
        location_clause = (
            f"based in or operating in {intake.location_str}"
            if not intake.is_remote
            else "which operates remotely / without a fixed physical location"
        )
        p1 = (
            f"What do you know about a business called \"{intake.business_name}\"? "
            f"If there are multiple businesses with this name, focus on the most "
            f"well-known one, but mention if the category doesn't match: it's "
            f"described as a {intake.ai_phrase} {location_clause}. "
            f"If you have no information about any business with this name, say exactly "
            f"'NO INFORMATION FOUND' and nothing else. "
            f"If you do have information, describe what you know in 2-3 sentences, "
            f"focusing on accuracy of services/positioning."
        )
        r1 = _call_claude(p1)
        raw["direct_knowledge"] = r1
        knows_business = "NO INFORMATION FOUND" not in r1.upper()

        # --- Prompt 2: Category + location recommendation check ---
        # This is the critical one - anchored to category, NOT business name.
        # For remote/distributed businesses, location-based phrasing ("in
        # Remote") is nonsensical - ask for well-known providers instead.
        if intake.is_remote:
            p2 = (
                f"Can you recommend some well-known {intake.ai_phrase_plural}? "
                f"List specific business names if you have any in mind, even if "
                f"you're not fully certain about current details."
            )
        else:
            p2 = (
                f"I'm looking for a {intake.ai_phrase} in {intake.location_str}. "
                f"Can you recommend a few options? List specific business names if you "
                f"have any in mind, even if you're not fully certain about current details."
            )
        r2 = _call_claude(p2, max_tokens=600)
        raw["recommendation_check"] = r2
        appears = intake.business_name.lower() in r2.lower()

        # --- Prompt 3: Competitor cross-check (category-anchored, niche-refined) ---
        # The broad category is the PRIMARY anchor (it has an established
        # competitive map for most businesses). The positioning phrase is used
        # to REFINE which subset of that category's players are relevant -
        # not as a new category in itself. This avoids over-triggering
        # "too emerging" on well-established categories just because the
        # business's specific marketing phrase sounds novel (e.g. a hotel
        # calling itself "AAA Four Diamond upscale waterfront" is still just
        # a hotel - competitors exist and are well-known).
        niche = intake.clarity_check_phrase or intake.ai_phrase
        location_clause_p3 = (
            f"in or near {intake.location_str}"
            if not intake.is_remote
            else "(this business operates remotely, so consider well-known players "
                 "in this space generally, not location-bound ones)"
        )
        p3 = (
            f"List 3-5 well-known {intake.ai_phrase_plural} (or close equivalents) that "
            f"compete with \"{intake.business_name}\" {location_clause_p3}. "
            f"\"{intake.business_name}\" positions itself as: \"{niche}\" - use this "
            f"only to pick relevant peers within the {intake.ai_phrase} category "
            f"(e.g. similar tier/quality level), not as a separate category. "
            f"If the broad category ({intake.ai_phrase}) itself has no established "
            f"players you can name confidently, say exactly "
            f"'NICHE TOO EMERGING' and nothing else - do not guess. "
            f"Otherwise, respond with ONLY a list of business names, one per line, "
            f"with NO other text - no descriptions, no caveats, no self-corrections, "
            f"no commentary before or after the list. If you reconsider an entry, "
            f"do not include the discarded version - output only your final list. "
            f"Each line must contain a business name and nothing else."
        )
        r3 = _call_claude(p3, max_tokens=300)
        raw["competitor_check"] = r3

        niche_too_emerging = "NICHE TOO EMERGING" in r3.upper()
        if niche_too_emerging:
            competitors = []
        else:
            competitors = _parse_competitor_list(r3)

        # --- Category mismatch / emerging-niche flags ---
        # Two distinct situations:
        # 1. "NICHE TOO EMERGING" - AI has no established competitive map for this
        #    niche at all. This is an OPPORTUNITY (no one's defined the category
        #    yet) as much as a risk, not a "mismatch" to fix.
        # 2. Mismatch - AI named real competitors, but they don't overlap with
        #    the business's self-identified competitors. Worth human review -
        #    may indicate AI has the wrong picture of the market.
        category_mismatch = False
        if niche_too_emerging:
            pass  # handled separately via niche_too_emerging field
        elif intake.known_competitors:
            overlap = set(c.lower() for c in intake.known_competitors) & set(c.lower() for c in competitors)
            if not overlap and competitors:
                category_mismatch = True  # not necessarily wrong, but worth a human look

        return AIVisibilityResult(
            knows_business=knows_business,
            knowledge_summary=r1,
            appears_in_recommendations=appears,
            recommendation_response=r2,
            competitors_mentioned=competitors,
            category_mismatch_flag=category_mismatch,
            niche_too_emerging=niche_too_emerging,
            raw_responses=raw
        )

    except RuntimeError as e:
        return AIVisibilityResult(
            knows_business=False,
            knowledge_summary="",
            appears_in_recommendations=False,
            recommendation_response="",
            competitors_mentioned=[],
            category_mismatch_flag=False,
            niche_too_emerging=False,
            raw_responses={},
            error=str(e)
        )


# =============================================================================
# DEEP SCAN: persona-based recommendation checks (premium tier)
#
# A single generic "recommend a X" prompt only tests one framing. Real
# customers ask differently depending on their situation - a price-sensitive
# shopper, someone with a specific/urgent need, someone seeking a related
# service, or a newcomer asking for general orientation. Each framing can
# surface different AI responses (different competitors, different
# visibility). This is the "personas" concept used by premium GEO platforms,
# implemented generically here so it works across the category taxonomy
# without per-business hardcoding.
#
# This roughly TRIPLES the API calls per scan (one extra call per persona),
# so it's intended for paid/deep-scan use, not the free web tool.
# =============================================================================

PERSONA_TEMPLATES = {
    "price_sensitive": (
        "I'm looking for an affordable, budget-friendly {category} {location_clause}. "
        "What are some good options that won't break the bank?"
    ),
    "quality_focused": (
        "I want the best, highest-quality {category} {location_clause} - "
        "I'm willing to pay more for excellent service/reputation. Any recommendations?"
    ),
    "newcomer": (
        "I just moved {location_clause_to} and need to find a good {category}. "
        "What would you recommend for someone new to the area?"
    ),
    "newcomer_remote": (
        "I'm new to working with {category_plural} and don't know who's reputable. "
        "What are some well-regarded options I should consider?"
    ),
    "urgent_need": (
        "I need a {category} {location_clause} as soon as possible - "
        "what are some reliable options I could contact today?"
    ),
}

# For remote businesses, "newcomer" (location-based framing) is replaced
# with "newcomer_remote" (industry-based framing). This mapping lets
# check_ai_visibility_deep() pick the right variant automatically.
_REMOTE_PERSONA_SUBSTITUTIONS = {
    "newcomer": "newcomer_remote",
}

# The default set of personas to run. Substitution-only targets (like
# "newcomer_remote", which only runs as a replacement for "newcomer" on
# remote businesses) are excluded here - otherwise they'd run twice for
# remote businesses (once as themselves, once as the substitution).
DEFAULT_PERSONAS = [
    key for key in PERSONA_TEMPLATES
    if key not in _REMOTE_PERSONA_SUBSTITUTIONS.values()
]


@dataclass
class PersonaResult:
    persona: str
    prompt: str
    response: str
    appears_in_recommendations: bool


def check_ai_visibility_deep(intake: BusinessIntake, personas: list = None) -> tuple:
    """Run the standard AI visibility check PLUS persona-variant recommendation
    checks. Returns (AIVisibilityResult, list[PersonaResult]).

    `personas` defaults to all of PERSONA_TEMPLATES' keys. Pass a subset to
    run fewer (e.g. ["price_sensitive", "quality_focused"] for a 2-persona scan).

    Cost note: this makes 1 extra API call per persona, on top of the 3 calls
    made by check_ai_visibility(). Default (4 personas) = 7 total calls vs 3
    for the standard scan - roughly 2.3x the cost.
    """
    base_result = check_ai_visibility(intake)

    if base_result.error or intake.needs_manual_review:
        return base_result, []

    if personas is None:
        personas = DEFAULT_PERSONAS

    location_clause = intake.location_phrase_for_ai  # "" if remote, "in City, ST" otherwise
    location_clause_to = (
        f"to the {intake.location_str} area" if not intake.is_remote else "into this industry"
    )

    persona_results = []
    for persona_key in personas:
        # For remote businesses, swap location-based personas for their
        # remote-appropriate equivalent (e.g. "newcomer" -> "newcomer_remote")
        effective_key = persona_key
        if intake.is_remote and persona_key in _REMOTE_PERSONA_SUBSTITUTIONS:
            effective_key = _REMOTE_PERSONA_SUBSTITUTIONS[persona_key]

        if effective_key not in PERSONA_TEMPLATES:
            continue
        template = PERSONA_TEMPLATES[effective_key]
        prompt = template.format(
            category=intake.ai_phrase,
            category_plural=intake.ai_phrase_plural,
            location_clause=location_clause,
            location_clause_to=location_clause_to,
        )
        # Clean up: collapse whitespace, then fix dangling space before
        # punctuation that results from an empty location_clause (remote businesses)
        prompt = re.sub(r"\s+", " ", prompt).strip()
        prompt = re.sub(r"\s+([.,?!])", r"\1", prompt)

        try:
            response = _call_claude(prompt, max_tokens=500)
        except RuntimeError as e:
            response = f"[Error running this persona check: {e}]"

        appears = intake.business_name.lower() in response.lower()

        persona_results.append(PersonaResult(
            persona=effective_key,
            prompt=prompt,
            response=response,
            appears_in_recommendations=appears,
        ))

    return base_result, persona_results


if __name__ == "__main__":
    import sys

    test = BusinessIntake(
        business_name="Woof Gang Bakery & Grooming Sylvania",
        category_key="fitness_wellness",          # closest fit - see CATEGORY_TAXONOMY
        city="Sylvania",
        region="OH",
        domain="woofgangbakery.com/pages/locations/sylvania",
        known_competitors=[],  # let AI surface its own picture
        positioning_phrase="dog grooming and pet bakery / boutique",
        custom_category_phrase="dog grooming salon and pet bakery"
    )

    if "--deep" in sys.argv:
        result, personas = check_ai_visibility_deep(test)

        if result.error:
            print(f"ERROR: {result.error}")
        else:
            print("=== STANDARD CHECK ===")
            print(f"Knows business: {result.knows_business}")
            print(f"Appears in general recommendations: {result.appears_in_recommendations}")
            print()
            print("=== PERSONA CHECKS ===")
            for p in personas:
                print(f"\n--- {p.persona} ---")
                print(f"Prompt: {p.prompt}")
                print(f"Appears in response: {p.appears_in_recommendations}")
                print(f"Response:\n{p.response}")
    else:
        result = check_ai_visibility(test)

        if result.error:
            print(f"ERROR: {result.error}")
        else:
            print("=== AI VISIBILITY CHECK ===")
            print(f"Knows business exists: {result.knows_business}")
            print(f"\nKnowledge summary:\n{result.knowledge_summary}")
            print(f"\nAppears in category recommendations: {result.appears_in_recommendations}")
            print(f"\nRecommendation response:\n{result.recommendation_response}")
            print(f"\nCompetitors mentioned by AI:\n{result.competitors_mentioned}")
            print(f"\nCategory mismatch flag: {result.category_mismatch_flag}")
            print()
            print("(Run with --deep flag for persona-based deep scan)")
