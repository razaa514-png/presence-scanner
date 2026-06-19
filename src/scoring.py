"""
Scoring module - converts raw scan results into:
1. Friction Score (0-100) - human-facing presence/UX health
2. AI Discovery Score (0-100) - GEO/AI visibility health
3. Composite score + letter grade

Scoring is intentionally simple and transparent for MVP - point deductions
per issue, with weights reflecting how much each factor matters. Weights
can be tuned later based on real client feedback / outcomes.
"""

from dataclasses import dataclass
from site_scan import SiteFrictionResult
from ai_visibility import AIVisibilityResult


# --- Friction score weights ---
# Each check below is worth points out of 100. Sum of max points = 100.
FRICTION_WEIGHTS = {
    "title_present": 10,
    "title_clear": 15,
    "meta_description": 10,
    "meta_description_length": 5,
    "schema_org": 25,          # heaviest weight - critical for both human SEO and AI
    "h1_present_single": 10,
    "nav_reasonable": 10,
    "contact_findable": 15,
}

# --- AI discovery score weights ---
AI_WEIGHTS = {
    "knows_business": 30,
    "appears_in_recommendations": 40,   # the big one - does AI actually suggest this business
    "no_category_mismatch": 15,
    "description_accurate": 15,         # proxy: did AI have *any* substantive knowledge (not just name)
}


@dataclass
class ScoreBreakdown:
    friction_score: int
    friction_max: int
    friction_details: dict          # check_name -> points earned
    friction_complete: bool

    ai_score: int
    ai_max: int
    ai_details: dict
    ai_complete: bool

    composite_score: int            # 0-100, or -1 if incomplete
    composite_grade: str            # letter grade, or "N/A" if incomplete
    composite_complete: bool


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"


def score_friction(result: SiteFrictionResult) -> tuple[int, dict]:
    """Returns (score, details dict of points earned per check)."""
    details = {}

    if not result.fetch_success:
        # Can't score what we can't fetch - return 0 with explanation
        return 0, {"fetch_failed": 0}

    # Title present
    details["title_present"] = FRICTION_WEIGHTS["title_present"] if result.title else 0

    # Title clear (matches positioning)
    details["title_clear"] = FRICTION_WEIGHTS["title_clear"] if result.title_clear else 0

    # Meta description present
    details["meta_description"] = FRICTION_WEIGHTS["meta_description"] if result.has_meta_description else 0

    # Meta description reasonable length (>= 50 chars)
    meta_len_ok = result.has_meta_description and len(result.meta_description) >= 50
    details["meta_description_length"] = FRICTION_WEIGHTS["meta_description_length"] if meta_len_ok else 0

    # Schema.org present
    details["schema_org"] = FRICTION_WEIGHTS["schema_org"] if result.has_schema_org else 0

    # H1 present and singular
    h1_ok = result.h1_count == 1
    details["h1_present_single"] = FRICTION_WEIGHTS["h1_present_single"] if h1_ok else 0

    # Nav reasonable (1-7 links, or no nav found gets partial credit if other signals strong)
    nav_ok = 1 <= result.nav_link_count <= 7
    details["nav_reasonable"] = FRICTION_WEIGHTS["nav_reasonable"] if nav_ok else 0

    # Contact findable
    details["contact_findable"] = FRICTION_WEIGHTS["contact_findable"] if result.contact_info_found else 0

    score = sum(details.values())
    return score, details


def score_ai_visibility(result: AIVisibilityResult) -> tuple[int, dict]:
    """Returns (score, details dict of points earned per check)."""
    details = {}

    if result.error:
        return 0, {"check_failed": 0}

    # Knows business exists at all
    details["knows_business"] = AI_WEIGHTS["knows_business"] if result.knows_business else 0

    # Appears in category+location recommendations - the big one
    details["appears_in_recommendations"] = (
        AI_WEIGHTS["appears_in_recommendations"] if result.appears_in_recommendations else 0
    )

    # No category mismatch flag
    details["no_category_mismatch"] = (
        AI_WEIGHTS["no_category_mismatch"] if not result.category_mismatch_flag else 0
    )

    # Description accuracy proxy: knowledge summary has substantive content
    # (more than just "NO INFORMATION FOUND" and longer than a trivial response)
    description_accurate = result.knows_business and len(result.knowledge_summary) > 30
    details["description_accurate"] = AI_WEIGHTS["description_accurate"] if description_accurate else 0

    score = sum(details.values())
    return score, details


def compute_scores(friction_result: SiteFrictionResult, ai_result: AIVisibilityResult) -> ScoreBreakdown:
    friction_score, friction_details = score_friction(friction_result)
    ai_score, ai_details = score_ai_visibility(ai_result)

    friction_complete = friction_result.fetch_success
    ai_complete = not bool(ai_result.error)

    if friction_complete and ai_complete:
        composite = round((friction_score + ai_score) / 2)
        grade = _grade(composite)
        composite_complete = True
    elif friction_complete and not ai_complete:
        # AI check failed - report friction score alone, flag incomplete
        composite = friction_score
        grade = _grade(composite) + " (friction only - AI check incomplete)"
        composite_complete = False
    elif ai_complete and not friction_complete:
        composite = ai_score
        grade = _grade(composite) + " (AI only - site scan incomplete)"
        composite_complete = False
    else:
        composite = -1
        grade = "N/A - scan incomplete"
        composite_complete = False

    return ScoreBreakdown(
        friction_score=friction_score,
        friction_max=100,
        friction_details=friction_details,
        friction_complete=friction_complete,
        ai_score=ai_score,
        ai_max=100,
        ai_details=ai_details,
        ai_complete=ai_complete,
        composite_score=composite,
        composite_grade=grade,
        composite_complete=composite_complete
    )


if __name__ == "__main__":
    from intake import BusinessIntake
    from site_scan import scan_html

    test = BusinessIntake(
        business_name="Elizabeth Koehler",
        category_key="marketing_agency",
        city="Remote / Worldwide",
        domain="elizabethkoehler.com",
        known_competitors=["Profound", "Scrunch", "Otterly.ai"],
        positioning_phrase="AI Visibility Strategy"
    )

    # Use local HTML test file
    with open("../test_data/elizabethkoehler.html", "r", encoding="utf-8") as f:
        html = f.read()
    friction_result = scan_html(html, test)

    # AI result will fail without API key - that's expected, demonstrates 0-score handling
    from ai_visibility import check_ai_visibility
    ai_result = check_ai_visibility(test)

    scores = compute_scores(friction_result, ai_result)

    print("=== FRICTION SCORE ===")
    print(f"Score: {scores.friction_score}/{scores.friction_max} (complete: {scores.friction_complete})")
    for check, points in scores.friction_details.items():
        max_pts = FRICTION_WEIGHTS.get(check, "-")
        print(f"  {check}: {points}/{max_pts}")

    print(f"\n=== AI DISCOVERY SCORE ===")
    print(f"Score: {scores.ai_score}/{scores.ai_max} (complete: {scores.ai_complete})")
    if ai_result.error:
        print(f"  (Could not run - {ai_result.error})")
    for check, points in scores.ai_details.items():
        max_pts = AI_WEIGHTS.get(check, "-")
        print(f"  {check}: {points}/{max_pts}")

    print(f"\n=== COMPOSITE ===")
    print(f"Score: {scores.composite_score}/100")
    print(f"Grade: {scores.composite_grade}")
    print(f"Complete: {scores.composite_complete}")
