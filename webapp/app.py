"""
Presence Health Check - Web App.

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python3 app.py

Then open http://127.0.0.1:5000 in a browser.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from flask import Flask, render_template, request

from intake import BusinessIntake, CATEGORY_TAXONOMY
from site_scan import scan_site
from ai_visibility import check_ai_visibility
from scoring import compute_scores, FRICTION_WEIGHTS, AI_WEIGHTS
from report import build_roadmap
import rate_limit


app = Flask(__name__)


def get_client_ip() -> str:
    """Get the requester's IP address.

    Checks X-Forwarded-For first (set by reverse proxies/load balancers in
    most production deployments), falling back to the direct connection IP
    (correct for local dev / direct connections).

    Note: X-Forwarded-For can be spoofed by the client if there's no trusted
    proxy in front of the app. If deploying behind a proxy (nginx, Cloudflare,
    etc.), configure it to overwrite rather than append to this header so the
    value can be trusted.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", categories=CATEGORY_TAXONOMY, error=None, form=None)


@app.route("/scan", methods=["POST"])
def scan():
    form = request.form

    business_name = form.get("business_name", "").strip()
    category_key = form.get("category_key", "").strip()
    city = form.get("city", "").strip()
    region = form.get("region", "").strip()
    domain = form.get("domain", "").strip()
    positioning_phrase = form.get("positioning_phrase", "").strip()
    custom_category_phrase = form.get("custom_category_phrase", "").strip()
    known_competitors_raw = form.get("known_competitors", "").strip()

    # --- Basic validation ---
    if not business_name or not category_key or not city or not domain:
        return render_template(
            "index.html",
            categories=CATEGORY_TAXONOMY,
            error="Please fill in business name, category, city, and domain.",
            form=form
        )

    if category_key not in CATEGORY_TAXONOMY:
        return render_template(
            "index.html",
            categories=CATEGORY_TAXONOMY,
            error="Please select a valid category.",
            form=form
        )

    known_competitors = [
        c.strip() for c in known_competitors_raw.split(",") if c.strip()
    ] if known_competitors_raw else []

    # --- Rate limit check (after validation, before running the actual scan) ---
    client_ip = get_client_ip()
    limit_result = rate_limit.check_and_record(client_ip)
    if not limit_result.allowed:
        return render_template(
            "index.html",
            categories=CATEGORY_TAXONOMY,
            error=limit_result.reason,
            form=form
        )

    # --- Build intake object ---
    intake = BusinessIntake(
        business_name=business_name,
        category_key=category_key,
        city=city,
        region=region or None,
        domain=domain,
        known_competitors=known_competitors,
        positioning_phrase=positioning_phrase,
        custom_category_phrase=custom_category_phrase
    )

    # --- Run the scan ---
    friction = scan_site(intake)
    ai = check_ai_visibility(intake)
    scores = compute_scores(friction, ai)
    roadmap = build_roadmap(intake, friction, ai, scores)

    return render_template(
        "results.html",
        intake=intake,
        friction=friction,
        ai=ai,
        scores=scores,
        roadmap=roadmap,
        friction_weights=FRICTION_WEIGHTS,
        ai_weights=AI_WEIGHTS,
    )


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("WARNING: ANTHROPIC_API_KEY is not set. AI Discovery checks will fail.")
        print("Set it with: export ANTHROPIC_API_KEY='sk-ant-...'")
        print()

    app.run(debug=True, host="127.0.0.1", port=5000)
