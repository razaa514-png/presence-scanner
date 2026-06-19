"""
Rate limiting for the Presence Health Check web app.

Two layers:
1. Per-IP limit - 3 scans per IP per day (resets at midnight UTC)
2. Global daily cap - total scans across ALL users per day, as a proxy for
   total API spend (each scan costs roughly $0.01-0.03, so a generous
   per-scan cost estimate is used to convert a dollar cap into a scan-count cap)

Storage: a single JSON file, reset/pruned daily. No database needed at this
scale. Not designed for high concurrency - fine for a small Flask dev server
or single-worker deployment. If this app gets real traffic, swap this for
Redis or a proper datastore.
"""

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass


# --- Configuration ---
MAX_SCANS_PER_IP_PER_DAY = 3
GLOBAL_DAILY_SPEND_CAP_USD = 5.00
ESTIMATED_COST_PER_SCAN_USD = 0.03  # conservative (high) estimate -
                                      # using the higher end of the $0.01-0.03
                                      # range means we stop BEFORE actually
                                      # hitting the dollar cap, not after.
GLOBAL_DAILY_SCAN_CAP = int(GLOBAL_DAILY_SPEND_CAP_USD / ESTIMATED_COST_PER_SCAN_USD)

_DATA_PATH = os.path.join(os.path.dirname(__file__), "rate_limit_data.json")


@dataclass
class RateLimitResult:
    allowed: bool
    reason: str = ""  # human-readable reason if not allowed


def _today_str() -> str:
    """Current date string (UTC), used as the reset boundary."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_data() -> dict:
    if not os.path.exists(_DATA_PATH):
        return {"date": _today_str(), "global_count": 0, "ip_counts": {}}

    try:
        with open(_DATA_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupted file - reset rather than crash the app
        return {"date": _today_str(), "global_count": 0, "ip_counts": {}}

    # Reset if it's a new day
    if data.get("date") != _today_str():
        return {"date": _today_str(), "global_count": 0, "ip_counts": {}}

    return data


def _save_data(data: dict) -> None:
    try:
        with open(_DATA_PATH, "w") as f:
            json.dump(data, f)
    except OSError:
        pass  # if we can't write, fail open rather than crash the app


def check_and_record(ip_address: str) -> RateLimitResult:
    """Check if a scan is allowed for this IP, and if so, record it.

    Call this BEFORE running a scan. If allowed=False, do not run the scan -
    show the reason to the user instead.

    This both checks AND records in one call to avoid race conditions where
    two requests both pass the check before either is recorded (not perfectly
    atomic for high concurrency, but adequate for this scale).
    """
    data = _load_data()

    # --- Global cap check (checked first - protects against any IP-spoofing) ---
    if data["global_count"] >= GLOBAL_DAILY_SCAN_CAP:
        return RateLimitResult(
            allowed=False,
            reason=(
                "We've hit our daily scan limit across all users. "
                "Please try again tomorrow, or contact us directly for a manual review."
            )
        )

    # --- Per-IP cap check ---
    ip_count = data["ip_counts"].get(ip_address, 0)
    if ip_count >= MAX_SCANS_PER_IP_PER_DAY:
        return RateLimitResult(
            allowed=False,
            reason=(
                f"You've reached the limit of {MAX_SCANS_PER_IP_PER_DAY} free scans "
                f"per day. Please try again tomorrow, or contact us directly if you'd "
                f"like additional scans now."
            )
        )

    # --- Allowed - record this scan ---
    data["global_count"] += 1
    data["ip_counts"][ip_address] = ip_count + 1
    _save_data(data)

    return RateLimitResult(allowed=True)


def get_status() -> dict:
    """Return current usage stats - useful for an admin/debug view."""
    data = _load_data()
    return {
        "date": data["date"],
        "global_count": data["global_count"],
        "global_cap": GLOBAL_DAILY_SCAN_CAP,
        "unique_ips_today": len(data["ip_counts"]),
        "per_ip_cap": MAX_SCANS_PER_IP_PER_DAY,
    }


if __name__ == "__main__":
    # Quick sanity test
    import tempfile

    # Use a temp file so we don't pollute real rate limit data
    _DATA_PATH = os.path.join(tempfile.gettempdir(), "rate_limit_test.json")
    if os.path.exists(_DATA_PATH):
        os.remove(_DATA_PATH)

    print(f"Global daily scan cap: {GLOBAL_DAILY_SCAN_CAP} (${GLOBAL_DAILY_SPEND_CAP_USD} / ${ESTIMATED_COST_PER_SCAN_USD})")
    print(f"Per-IP daily cap: {MAX_SCANS_PER_IP_PER_DAY}")
    print()

    test_ip = "1.2.3.4"
    for i in range(MAX_SCANS_PER_IP_PER_DAY + 1):
        result = check_and_record(test_ip)
        print(f"Scan {i+1} for {test_ip}: allowed={result.allowed} {result.reason}")

    print()
    print("Status:", get_status())

    os.remove(_DATA_PATH)
