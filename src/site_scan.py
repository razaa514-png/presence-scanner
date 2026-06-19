"""
Site Friction Scanner (the "human side" of the Presence Health Check).

Checks signals that affect whether a human visitor can easily understand
and navigate the business's site - independent of AI visibility.

Checks performed:
- Title tag clarity (does it state what the business does?)
- Meta description presence/quality
- Schema.org structured data presence (also feeds the AI/GEO side)
- Heading structure (H1 presence, hierarchy)
- Navigation link count (too many = confusing)
- Contact info findability (phone/email in text)
- Page load - basic response check
"""

import re
import urllib.request
import urllib.error
from dataclasses import dataclass
from intake import BusinessIntake


@dataclass
class SiteFrictionResult:
    fetch_success: bool
    status_code: int
    title: str
    title_clear: bool          # does title contain category-relevant words?
    meta_description: str
    has_meta_description: bool
    has_schema_org: bool
    schema_types_found: list
    h1_count: int
    h1_text: list
    nav_link_count: int
    contact_info_found: bool
    contact_methods: list
    issues: list                # human-readable list of problems found
    error: str = ""


def _empty_result(issues, error=""):
    return SiteFrictionResult(
        fetch_success=False, status_code=0, title="", title_clear=False,
        meta_description="", has_meta_description=False, has_schema_org=False,
        schema_types_found=[], h1_count=0, h1_text=[], nav_link_count=0,
        contact_info_found=False, contact_methods=[],
        issues=issues, error=error
    )


def _fetch_html(url: str) -> str:
    """Fetch raw HTML from a URL. Adds https:// if missing scheme."""
    if not url.startswith("http"):
        url = "https://" + url

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (PresenceHealthCheck/1.0)"}
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _analyze_html(html: str, intake: BusinessIntake, status_code: int) -> SiteFrictionResult:
    """Core analysis logic - works on any HTML string, fetched or local."""
    issues = []

    # --- Title tag ---
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""
    if not title:
        issues.append("No <title> tag found - this is critical for both human and AI understanding.")

    # Title clarity: does it contain words related to how the business positions itself?
    title_clear = False
    clarity_phrase = intake.clarity_check_phrase
    if title and clarity_phrase:
        clarity_words = clarity_phrase.lower().split()
        title_lower = title.lower()
        title_clear = any(w in title_lower for w in clarity_words if len(w) > 3)
        if not title_clear:
            issues.append(
                f"Title tag ('{title}') doesn't clearly include your stated positioning "
                f"('{clarity_phrase}'). Visitors and AI engines rely on titles to quickly "
                f"understand what you do - if your key positioning terms aren't there, "
                f"you may be harder to match to relevant searches."
            )

    # --- Meta description ---
    meta_match = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL
    )
    meta_description = meta_match.group(1).strip() if meta_match else ""
    has_meta_description = bool(meta_description)
    if not has_meta_description:
        issues.append("No meta description found - AI engines and search results rely on this for summaries.")
    elif len(meta_description) < 50:
        issues.append("Meta description is very short - may not give AI/search engines enough context.")

    # --- Schema.org structured data ---
    schema_blocks = re.findall(
        r'<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL
    )
    has_schema_org = len(schema_blocks) > 0
    schema_types_found = []
    for block in schema_blocks:
        types = re.findall(r'"@type"\s*:\s*"([^"]+)"', block)
        for t in types:
            if t not in schema_types_found:  # dedupe, preserve first-seen order
                schema_types_found.append(t)
    if not has_schema_org:
        issues.append(
            "No structured data (schema.org) found in this scan. This is one of the "
            "strongest signals AI engines use to understand what your business is and "
            "does - missing it is a direct hit to AI discoverability. "
            "Note: if this page is built with a JavaScript framework, schema markup "
            "may be added dynamically after the page loads and would not appear in "
            "saved page-source HTML - this finding should be verified by checking the "
            "live rendered page (e.g. via browser dev tools or Google's Rich Results "
            "Test) before concluding it's truly absent."
        )

    # --- Heading structure ---
    h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    h1_text = [re.sub(r"<[^>]+>", "", h).strip() for h in h1_matches]
    h1_count = len(h1_text)
    if h1_count == 0:
        issues.append("No H1 heading found - both visitors and AI use this to quickly identify page purpose.")
    elif h1_count > 1:
        issues.append(f"Multiple H1 tags found ({h1_count}) - can confuse content hierarchy.")

    # --- Navigation link count (rough proxy: links inside <nav>) ---
    nav_match = re.search(r"<nav[^>]*>(.*?)</nav>", html, re.IGNORECASE | re.DOTALL)
    nav_link_count = 0
    if nav_match:
        nav_link_count = len(re.findall(r"<a\s", nav_match.group(1), re.IGNORECASE))
        if nav_link_count > 7:
            issues.append(
                f"Navigation has {nav_link_count} links - more than ~7 nav items can "
                f"overwhelm visitors and dilute focus on key actions."
            )
    else:
        issues.append("No <nav> element found - navigation structure may be unclear or non-standard.")

    # --- Contact info findability ---
    contact_methods = []
    if re.search(r"mailto:", html, re.IGNORECASE):
        contact_methods.append("email link")
    if re.search(r"tel:", html, re.IGNORECASE):
        contact_methods.append("phone link")
    if re.search(r"\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", html):
        contact_methods.append("phone number in text")

    contact_info_found = len(contact_methods) > 0
    if not contact_info_found:
        issues.append(
            "No clear contact method found (no mailto link, tel link, or visible phone number). "
            "Visitors and AI engines both struggle to find how to reach you."
        )

    return SiteFrictionResult(
        fetch_success=True,
        status_code=status_code,
        title=title,
        title_clear=title_clear,
        meta_description=meta_description,
        has_meta_description=has_meta_description,
        has_schema_org=has_schema_org,
        schema_types_found=schema_types_found,
        h1_count=h1_count,
        h1_text=h1_text,
        nav_link_count=nav_link_count,
        contact_info_found=contact_info_found,
        contact_methods=contact_methods,
        issues=issues
    )


def scan_html(html: str, intake: BusinessIntake) -> SiteFrictionResult:
    """Run friction checks on already-fetched HTML content. Allows testing
    against local/offline HTML without a live fetch."""
    return _analyze_html(html, intake, status_code=200)


def scan_site(intake: BusinessIntake) -> SiteFrictionResult:
    """Fetch a domain live and run friction checks on it."""
    if not intake.domain:
        return _empty_result(["No domain provided."], error="No domain provided")

    try:
        html = _fetch_html(intake.domain)
    except urllib.error.HTTPError as e:
        return _empty_result(
            [f"Site returned error status {e.code} - may be unreachable or blocking scanners."],
            error=f"HTTP {e.code}"
        )
    except Exception as e:
        return _empty_result([f"Could not fetch site: {str(e)}"], error=str(e))

    return _analyze_html(html, intake, status_code=200)


if __name__ == "__main__":
    import sys

    test = BusinessIntake(
        business_name="Elizabeth Koehler",
        category_key="marketing_agency",
        city="Remote / Worldwide",
        domain="elizabethkoehler.com",
        known_competitors=["Profound", "Scrunch", "Otterly.ai"],
        positioning_phrase="AI Visibility Strategy"
    )

    # If a local HTML file path is passed as an argument, test against that
    # instead of a live fetch (useful since live fetch may be blocked in sandboxes).
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        result = scan_html(html, test)
    else:
        result = scan_site(test)

    print("=== SITE FRICTION SCAN ===")
    print(f"Fetch success: {result.fetch_success}")
    if result.error:
        print(f"Error: {result.error}")
    print(f"\nTitle: {result.title!r}")
    print(f"Title clear (matches category): {result.title_clear}")
    print(f"\nMeta description: {result.meta_description!r}")
    print(f"Has meta description: {result.has_meta_description}")
    print(f"\nHas schema.org data: {result.has_schema_org}")
    print(f"Schema types found: {result.schema_types_found}")
    print(f"\nH1 count: {result.h1_count}")
    print(f"H1 text: {result.h1_text}")
    print(f"\nNav link count: {result.nav_link_count}")
    print(f"\nContact methods found: {result.contact_methods}")
    print(f"\n=== ISSUES FOUND ({len(result.issues)}) ===")
    for i, issue in enumerate(result.issues, 1):
        print(f"{i}. {issue}")
