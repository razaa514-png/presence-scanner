"""
Report generator - converts scan results + scores into a client-facing
Markdown report (renders as HTML in most viewers, easy to email/display).

Two report levels:
- TEASER (free): scores, grade, top 2-3 issues, CTA toward paid report
- FULL (paid): all issues, plain-language explanations, prioritized roadmap

Both share the same underlying data - the FULL report is a superset.
"""

from intake import BusinessIntake
from site_scan import SiteFrictionResult
from ai_visibility import AIVisibilityResult
from scoring import ScoreBreakdown


def _score_bar(score: int, max_score: int = 100, width: int = 20) -> str:
    """Simple text-based score bar for markdown."""
    filled = round((score / max_score) * width) if max_score else 0
    return "█" * filled + "░" * (width - filled)


def _completeness_note(scores: ScoreBreakdown) -> str:
    if scores.composite_complete:
        return ""
    notes = []
    if not scores.friction_complete:
        notes.append("the site scan could not be completed")
    if not scores.ai_complete:
        notes.append("the AI visibility check could not be completed")
    return (
        f"\n> **Note:** {', and '.join(notes)} for this scan. "
        f"The score shown reflects only the portion that completed successfully.\n"
    )


def generate_teaser_report(
    intake: BusinessIntake,
    friction: SiteFrictionResult,
    ai: AIVisibilityResult,
    scores: ScoreBreakdown
) -> str:
    """Free teaser report - scores + top issues + CTA."""

    lines = []
    lines.append(f"# Presence Health Check: {intake.business_name}")
    lines.append(f"*{intake.category_label} — {intake.location_str}*")
    lines.append("")
    lines.append(_completeness_note(scores))

    # --- Score summary ---
    lines.append("## Your Scores")
    lines.append("")
    if scores.composite_complete:
        lines.append(f"**Overall Grade: {scores.composite_grade} ({scores.composite_score}/100)**")
        lines.append("")
    lines.append(f"**Search Foundations** (can people use and navigate your site easily?)")
    lines.append(f"`{_score_bar(scores.friction_score)}` {scores.friction_score}/100")
    lines.append("")
    if scores.ai_complete:
        lines.append(f"**AI Discovery** (do AI engines like ChatGPT and Gemini know and recommend you?)")
        lines.append(f"`{_score_bar(scores.ai_score)}` {scores.ai_score}/100")
    else:
        lines.append(f"**AI Discovery**: *not completed in this scan*")
    lines.append("")

    # --- Top issues (max 3 for teaser) ---
    all_issues = list(friction.issues)
    if scores.ai_complete and not ai.appears_in_recommendations:
        location_bit = f" in {intake.location_str}" if not intake.is_remote else ""
        all_issues.insert(0,
            f"When asked for {intake.ai_phrase} recommendations{location_bit}, "
            f"AI did not mention {intake.business_name}. This means potential customers "
            f"asking AI assistants for recommendations may never hear about you."
        )
    if scores.ai_complete and not ai.knows_business:
        all_issues.insert(0,
            f"AI engines currently have no information about {intake.business_name} at all. "
            f"You're effectively invisible to anyone using AI to research or find businesses "
            f"like yours."
        )

    top_issues = all_issues[:3]

    if top_issues:
        lines.append("## Top Issues Found")
        lines.append("")
        for i, issue in enumerate(top_issues, 1):
            lines.append(f"{i}. {issue}")
        lines.append("")

        remaining = len(all_issues) - len(top_issues)
        if remaining > 0:
            lines.append(f"*...and {remaining} more issue(s) identified in this scan.*")
            lines.append("")
    else:
        lines.append("## Top Issues Found")
        lines.append("")
        lines.append("No major issues found in this scan. Your foundation looks solid - ")
        lines.append("the full report includes additional refinement opportunities.")
        lines.append("")

    # --- CTA ---
    lines.append("---")
    lines.append("")
    lines.append("### Want the Full Report?")
    lines.append("")
    lines.append(
        "This teaser shows a snapshot. The full Presence Health Check includes:"
    )
    lines.append("")
    lines.append("- Every issue found, explained in plain language")
    lines.append("- A prioritized action plan (what to fix first, and why)")
    lines.append("- Full AI visibility detail: exactly what AI engines say about you today")
    lines.append("- Competitor comparison within your actual category")
    lines.append("")
    lines.append("[Get your full report →]")
    lines.append("")

    return "\n".join(lines)


def build_roadmap(intake: BusinessIntake, friction: SiteFrictionResult, ai: AIVisibilityResult, scores: ScoreBreakdown) -> list:
    """Build a prioritized list of (priority, title, explanation) tuples.

    Shared between the Markdown report and the web app's HTML results page,
    so the recommendation logic only needs to be maintained in one place.
    """
    # Total failure: neither check completed - don't claim "no issues found"
    if not scores.friction_complete and not scores.ai_complete:
        return [(
            "Error",
            "Scan could not be completed",
            "Neither the site scan nor the AI visibility check completed "
            "successfully, so no findings are available. Please check the "
            "domain and try again, or verify the scanner configuration."
        )]

    roadmap = []

    # Highest priority: not appearing in AI recommendations at all
    if scores.ai_complete and not ai.knows_business:
        roadmap.append((
            "Critical",
            "Establish baseline AI presence",
            f"AI engines have no information about {intake.business_name}. "
            f"Priority one is creating the structured signals (schema markup, "
            f"consistent business descriptions across the web) that allow AI "
            f"systems to learn who you are."
        ))
    elif scores.ai_complete and not ai.appears_in_recommendations:
        location_bit = f" in {intake.location_str}" if not intake.is_remote else ""
        roadmap.append((
            "High",
            "Improve AI recommendation visibility",
            f"AI knows about you but doesn't recommend you for {intake.ai_phrase} "
            f"searches{location_bit}. This typically requires stronger "
            f"category/{'positioning' if intake.is_remote else 'location'} signals "
            f"and citation-worthy content."
        ))

    # Emerging niche - first-mover opportunity
    if scores.ai_complete and ai.niche_too_emerging:
        roadmap.append((
            "Opportunity",
            "Claim category leadership in an undefined niche",
            f"AI has no established competitive map for \"{intake.clarity_check_phrase}\". "
            f"Publishing consistent, citable content that defines this category - and "
            f"positions you within it - could establish you as the reference point AI "
            f"engines default to as the space matures."
        ))

    # Schema is high-leverage for both scores
    if friction.fetch_success and not friction.has_schema_org:
        roadmap.append((
            "Critical",
            "Add structured data (schema.org)",
            "This is the single highest-leverage fix - it directly helps both "
            "human search results and AI understanding of your business."
        ))

    # Title/meta issues
    if friction.fetch_success and not friction.title_clear:
        roadmap.append((
            "Medium",
            "Clarify title tag",
            "Your title doesn't include your core positioning terms - this is "
            "a quick fix with immediate benefit to both search and AI matching."
        ))

    if friction.fetch_success and not friction.has_meta_description:
        roadmap.append((
            "Medium",
            "Add a meta description",
            "AI and search engines use this to summarize your page - currently "
            "they have nothing to work with."
        ))

    if friction.fetch_success and not friction.contact_info_found:
        roadmap.append((
            "High",
            "Make contact information findable",
            "Visitors and AI systems alike can't easily determine how to reach you."
        ))

    if not roadmap:
        roadmap.append((
            "Low",
            "Maintain and monitor",
            "No critical issues found. Recommend periodic re-scans as AI engines "
            "and search algorithms evolve - what works today may not in 6 months."
        ))

    return roadmap


def generate_full_report(
    intake: BusinessIntake,
    friction: SiteFrictionResult,
    ai: AIVisibilityResult,
    scores: ScoreBreakdown
) -> str:
    """Full paid report - all findings, explanations, roadmap."""

    lines = []
    lines.append(f"# Presence Health Check: {intake.business_name}")
    lines.append(f"*{intake.category_label} — {intake.location_str}*")
    if intake.positioning_phrase:
        lines.append(f"*Positioning: {intake.positioning_phrase}*")
    lines.append("")
    lines.append(_completeness_note(scores))

    # --- Score summary ---
    lines.append("## Scores")
    lines.append("")
    if scores.composite_complete:
        lines.append(f"**Overall Grade: {scores.composite_grade} ({scores.composite_score}/100)**")
        lines.append("")

    lines.append(f"### Search Foundations: {scores.friction_score}/100")
    lines.append(f"`{_score_bar(scores.friction_score)}`")
    lines.append("")
    for check, points in scores.friction_details.items():
        from scoring import FRICTION_WEIGHTS
        max_pts = FRICTION_WEIGHTS.get(check, 0)
        status = "✓" if points == max_pts and max_pts > 0 else "✗"
        readable = check.replace("_", " ").title()
        lines.append(f"- {status} {readable}: {points}/{max_pts}")
    lines.append("")

    if scores.ai_complete:
        lines.append(f"### AI Discovery: {scores.ai_score}/100")
        lines.append(f"`{_score_bar(scores.ai_score)}`")
        lines.append("")
        for check, points in scores.ai_details.items():
            from scoring import AI_WEIGHTS
            max_pts = AI_WEIGHTS.get(check, 0)
            status = "✓" if points == max_pts and max_pts > 0 else "✗"
            readable = check.replace("_", " ").title()
            lines.append(f"- {status} {readable}: {points}/{max_pts}")
        lines.append("")
    else:
        lines.append(f"### AI Discovery: Not completed")
        lines.append(f"*Error: {ai.error}*")
        lines.append("")

    # --- Detailed findings: Search Foundations ---
    lines.append("---")
    lines.append("")
    lines.append("## Search Foundations — Detailed Findings")
    lines.append("")
    if friction.fetch_success:
        lines.append(f"**Title tag:** \"{friction.title}\"")
        lines.append(f"**Meta description:** \"{friction.meta_description}\"")
        lines.append(f"**Structured data (schema.org) types found:** {', '.join(friction.schema_types_found) or 'None'}")
        lines.append(f"**H1 heading(s):** {', '.join(friction.h1_text) or 'None'}")
        lines.append(f"**Navigation links:** {friction.nav_link_count}")
        lines.append(f"**Contact methods found:** {', '.join(friction.contact_methods) or 'None'}")
        lines.append("")

        if friction.issues:
            lines.append("### Issues & Why They Matter")
            lines.append("")
            for issue in friction.issues:
                lines.append(f"- {issue}")
            lines.append("")
        else:
            lines.append("**No issues found.** Your site's foundational structure is solid.")
            lines.append("")
    else:
        lines.append(f"*Could not scan site: {friction.error}*")
        lines.append("")

    # --- Detailed findings: AI Discovery ---
    lines.append("---")
    lines.append("")
    lines.append("## AI Discovery — Detailed Findings")
    lines.append("")

    if scores.ai_complete:
        lines.append("### What AI Knows About You")
        lines.append("")
        if ai.knows_business:
            lines.append(f"AI has the following information about {intake.business_name}:")
            lines.append("")
            lines.append(f"> {ai.knowledge_summary}")
        else:
            lines.append(
                f"**AI has no information about {intake.business_name}.** "
                f"When asked directly, it returned no relevant results. This means "
                f"you have no presence in the data these systems draw from."
            )
        lines.append("")

        lines.append("### Do You Appear in Recommendations?")
        lines.append("")
        if ai.appears_in_recommendations:
            location_bit = f" in {intake.location_str}" if not intake.is_remote else ""
            lines.append(
                f"**Yes.** When asked for {intake.ai_phrase} recommendations{location_bit}, "
                f"{intake.business_name} was mentioned."
            )
        else:
            lines.append(
                f"**No.** When asked \"{intake.recommendation_question_display}\", "
                f"{intake.business_name} did not appear. Here's what AI suggested instead:"
            )
            lines.append("")
            lines.append(f"> {ai.recommendation_response}")
        lines.append("")

        lines.append("### Who AI Considers Your Competitors")
        lines.append("")
        if ai.niche_too_emerging:
            lines.append(
                f"**AI does not have an established competitive map for your specific "
                f"niche (\"{intake.clarity_check_phrase}\").** When asked directly, it "
                f"declined to name competitors rather than risk inventing inaccurate ones."
            )
            lines.append("")
            lines.append(
                "> **This cuts both ways.** On one hand, if a potential client asks AI "
                "\"who are the leading providers of [your niche]?\", there's currently "
                "no established list for you to be on or off of - you could be left out "
                "of comparisons entirely simply because the category isn't mapped yet. "
                "On the other hand, this is a genuine first-mover opportunity: whoever "
                "AI engines learn to associate with this niche first - through consistent "
                "content, citations, and structured data - is likely to become the "
                "default reference point as the category matures."
            )
            lines.append("")
        elif ai.competitors_mentioned:
            for comp in ai.competitors_mentioned:
                lines.append(f"- {comp}")
            lines.append("")
            if ai.category_mismatch_flag:
                lines.append(
                    "> **Flag:** The competitors AI associates with your category don't "
                    "overlap with the competitors you identified. This may indicate AI "
                    "has an inaccurate picture of your market position - worth a closer "
                    "human review."
                )
                lines.append("")
        else:
            lines.append("*No competitors identified in this scan.*")
            lines.append("")
    else:
        lines.append(f"*AI visibility check did not complete: {ai.error}*")
        lines.append("")

    # --- Prioritized roadmap ---
    lines.append("---")
    lines.append("")
    lines.append("## Prioritized Action Plan")
    lines.append("")

    roadmap = build_roadmap(intake, friction, ai, scores)

    for priority, title, explanation in roadmap:
        lines.append(f"**[{priority}] {title}**")
        lines.append(f"{explanation}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    from intake import BusinessIntake
    from site_scan import scan_html
    from ai_visibility import check_ai_visibility
    from scoring import compute_scores

    test = BusinessIntake(
        business_name="Elizabeth Koehler",
        category_key="marketing_agency",
        city="Remote / Worldwide",
        domain="elizabethkoehler.com",
        known_competitors=["Profound", "Scrunch", "Otterly.ai"],
        positioning_phrase="AI Visibility Strategy"
    )

    with open("../test_data/elizabethkoehler.html", "r", encoding="utf-8") as f:
        html = f.read()

    friction = scan_html(html, test)
    ai = check_ai_visibility(test)
    scores = compute_scores(friction, ai)

    print("=" * 60)
    print("TEASER REPORT")
    print("=" * 60)
    print(generate_teaser_report(test, friction, ai, scores))

    print("\n" + "=" * 60)
    print("FULL REPORT")
    print("=" * 60)
    print(generate_full_report(test, friction, ai, scores))
