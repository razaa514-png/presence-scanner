"""
Presence Health Check - CLI entry point.

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python3 run_scan.py

Edit the BUSINESS section below to scan a different business.
For sites that block automated fetches (common - many sites return 403 to
scanners), save the page's HTML manually and use the local_html_path option.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from intake import BusinessIntake, CATEGORY_TAXONOMY
from site_scan import scan_site, scan_html
from ai_visibility import check_ai_visibility
from scoring import compute_scores
from report import generate_teaser_report, generate_full_report


# =============================================================
# EDIT THIS SECTION FOR EACH BUSINESS YOU WANT TO SCAN
# =============================================================

BUSINESS = BusinessIntake(
    business_name="Anthropic",
    category_key="saas_software",          # see CATEGORY_TAXONOMY keys below
    city="San Francisco",
    region="CA",
    domain="anthropic.com",
    known_competitors=["OpenAI", "Google DeepMind", "Meta AI"],
    positioning_phrase="AI safety company building Claude",
    custom_category_phrase="AI research and safety company"
)

# If the live site blocks scanners (403), set this to a local HTML file path
# (save the page source with Ctrl+S / "View Source" / browser dev tools).
LOCAL_HTML_PATH = None   # try live fetch first - if it 403s, save HTML to test_data/anthropic.html and set this

# Which report to print: "teaser" or "full"
REPORT_TYPE = "full"

# =============================================================


def print_category_list():
    print("Available categories:")
    for key, val in CATEGORY_TAXONOMY.items():
        print(f"  {key}: {val['label']}")


def main():
    if "--categories" in sys.argv:
        print_category_list()
        return

    print(f"Scanning: {BUSINESS.business_name} ({BUSINESS.category_label})")
    print(f"Domain: {BUSINESS.domain}")
    print("-" * 60)

    # --- Site friction scan ---
    if LOCAL_HTML_PATH:
        print(f"Reading local HTML from {LOCAL_HTML_PATH}...")
        with open(LOCAL_HTML_PATH, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        friction = scan_html(html, BUSINESS)
    else:
        print("Fetching live site...")
        friction = scan_site(BUSINESS)
        if not friction.fetch_success:
            print(f"  Live fetch failed ({friction.error}).")
            print("  Tip: if this site blocks scanners (common), save the page's")
            print("  HTML manually and set LOCAL_HTML_PATH at the top of this file.")

    # --- AI visibility check ---
    print("Checking AI visibility (this makes a few API calls, may take ~10-20s)...")
    ai = check_ai_visibility(BUSINESS)
    if ai.error:
        print(f"  AI check failed: {ai.error}")

    # --- Scoring ---
    scores = compute_scores(friction, ai)

    # --- Report ---
    print("-" * 60)
    if REPORT_TYPE == "teaser":
        report = generate_teaser_report(BUSINESS, friction, ai, scores)
    else:
        report = generate_full_report(BUSINESS, friction, ai, scores)

    print(report)

    # Also save to file, in a dedicated "reports" folder (created if needed)
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_name = BUSINESS.business_name.replace(" ", "_").lower()
    out_path = os.path.join(reports_dir, f"{safe_name}_{timestamp}.md")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[Saved report to {out_path}]")


if __name__ == "__main__":
    main()
