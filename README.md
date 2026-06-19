# Presence Health Check — Scanner Prototype

A working prototype that scores a business on two axes:

1. **Human Findability** ("friction score") — site structure, navigation, contact info, schema markup, title/meta clarity
2. **AI Discovery** ("GEO score") — whether AI engines (currently Claude, via API) know about and recommend the business

Both feed into a composite score and a Markdown report.

## Setup

1. **Install Python 3.10+** if you don't have it.
2. **Get an Anthropic API key:**
   - Go to https://console.anthropic.com
   - Sign in, go to "API Keys" in the sidebar, click "Create Key"
   - Copy the key (starts with `sk-ant-`)
   - Set up billing on the console (pay-as-you-go; testing a few businesses costs well under $1)
3. **Set your API key as an environment variable:**

   On Mac/Linux:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-your-key-here"
   ```

   On Windows (PowerShell):
   ```powershell
   $env:ANTHROPIC_API_KEY="sk-ant-your-key-here"
   ```

   (You'll need to set this every time you open a new terminal, or add it to
   your shell profile / a `.env` file with a tool like `python-dotenv`.)

## Running a Scan

```bash
python3 run_scan.py
```

This runs the bundled test case (Elizabeth Koehler's site, using a local copy
of her HTML) and prints + saves a full report.

## Scanning a Different Business

Open `run_scan.py` and edit the `BUSINESS` section near the top:

```python
BUSINESS = BusinessIntake(
    business_name="Your Business Name",
    category_key="home_services",       # see categories below
    city="Toledo",
    region="OH",
    domain="yourbusiness.com",
    known_competitors=["Competitor A", "Competitor B"],
    positioning_phrase="24/7 Emergency Plumbing",  # how you describe yourselves
    custom_category_phrase=""  # optional: if no taxonomy category fits well,
                                 # set this to override the phrase used in AI
                                 # prompts (e.g. "commercial sign company")
)
```

To see available categories:
```bash
python3 run_scan.py --categories
```

### If the live site won't load (403 errors)

Many sites block automated requests. If `scan_site()` fails with a 403 or
similar:

1. Open the site in your browser
2. Right-click → "View Page Source" (or Ctrl+U), or use browser dev tools
3. Save the HTML to a file, e.g. `test_data/yoursite.html`
4. In `run_scan.py`, set:
   ```python
   LOCAL_HTML_PATH = "test_data/yoursite.html"
   ```

## Running the Web App

A simple web interface is available in `webapp/`. It reuses all the same
scanning logic, with an intake form and a results page in the browser.

```bash
pip install flask --break-system-packages
cd webapp
python3 app.py
```

Then open **http://127.0.0.1:5000** in your browser. The form lets you enter
business details (matching the CLI's `BusinessIntake` fields) and shows the
full report - scores, findings, and action plan - as a styled web page.

This runs a local development server (only accessible from your own
computer). Stop it with Ctrl+C in the terminal.

Remember to set `ANTHROPIC_API_KEY` first (same as the CLI, see Setup above)
or the AI Discovery section won't be able to run.

**Note:** the web app's site scan uses live fetching only (no local-HTML
fallback like the CLI). If a site returns a 403, the Human Findability
section will show "could not scan site" - this is a known limitation for
sites that block automated requests.

## Rate Limiting & Cost Protection

Since each scan makes real (billed) Anthropic API calls, the web app
includes basic abuse protection in `webapp/rate_limit.py`:

- **Per-IP limit**: 3 scans per IP address per day
- **Global daily cap**: a total scan count across all users, calculated from
  a $5/day spend cap and a conservative per-scan cost estimate ($0.03) -
  currently 166 scans/day total

Both reset at midnight UTC. Usage data is stored in
`webapp/rate_limit_data.json` (created automatically, gitignored-style -
don't commit this file, it's just local state).

**Limitations to be aware of:**
- IP-based limiting can be bypassed by VPNs/proxies - the global daily cap
  is the real backstop against this, since it limits total cost regardless
  of how many different IPs are used
- If deploying behind a reverse proxy (nginx, Cloudflare, etc.), make sure
  it sets `X-Forwarded-For` correctly (overwriting, not appending) or IP
  detection won't be accurate
- This uses simple file-based storage, fine for low-to-moderate traffic on a
  single server. If you outgrow this, swap `rate_limit.py`'s storage for
  Redis or a database - the `check_and_record()` / `get_status()` interface
  can stay the same

To adjust the limits, edit the constants at the top of `rate_limit.py`:
`MAX_SCANS_PER_IP_PER_DAY`, `GLOBAL_DAILY_SPEND_CAP_USD`, and
`ESTIMATED_COST_PER_SCAN_USD`.

## What Each Module Does

- `src/intake.py` — controlled category taxonomy + business info structure.
  Categories anchor every AI prompt to avoid mismatched-industry results
  (the "ranked among hotels" problem).
- `src/site_scan.py` — fetches/parses HTML for friction signals (title,
  meta description, schema.org, headings, nav, contact info).
- `src/ai_visibility.py` — queries Claude with category-anchored prompts to
  check if the business is known/recommended by AI.
- `src/scoring.py` — converts raw results into 0-100 scores + letter grade.
  Handles partial/incomplete scans without producing misleading scores.
- `src/report.py` — generates Markdown reports (teaser + full versions).
- `run_scan.py` — CLI entry point that ties it all together.

## Deep Scan (Persona-Based, Premium Tier)

For paid engagements, `src/ai_visibility.py` includes a deep-scan mode that
tests AI visibility from multiple customer perspectives ("personas"), not
just one generic query:

- **price_sensitive** - "I'm looking for an affordable X, what are some good options?"
- **quality_focused** - "I want the best X, willing to pay more - recommendations?"
- **newcomer** - "I just moved here and need a good X - what would you recommend?"
  (for remote/distributed businesses, this becomes "I'm new to working with
  X's and don't know who's reputable")
- **urgent_need** - "I need an X ASAP - reliable options I could contact today?"

Each persona may surface different AI responses (different competitors,
different visibility) - a single generic check can miss this variation.

**Cost note:** this roughly triples the API calls compared to the standard
scan (4 extra calls for the default 4 personas, vs 3 calls for a standard
scan - about 2.3x the cost). Not used by the free web tool; run manually for
deep/paid audits:

```bash
cd src
python3 ai_visibility.py --deep
```

Edit the `test` business at the bottom of `ai_visibility.py`, or call
`check_ai_visibility_deep(intake)` directly from your own script - it
returns `(AIVisibilityResult, list[PersonaResult])`. You can also pass a
subset of personas, e.g.
`check_ai_visibility_deep(intake, personas=["price_sensitive", "quality_focused"])`
to run fewer than the default 4.


## Known Limitations (MVP Stage)

- AI visibility currently checks only Claude. Real GEO products check
  ChatGPT, Gemini, Perplexity too — adding those means adding their
  respective API calls (similar pattern to `ai_visibility.py`).
- No Google Places / PageSpeed integration yet (useful for NAP consistency,
  page speed scoring) — these require Google Cloud API keys.
- Category taxonomy is intentionally small — expand `CATEGORY_TAXONOMY` in
  `intake.py` as needed.
- Scoring weights are a first pass — tune based on real client feedback.
- Output is Markdown. Convert to HTML/PDF for client-facing delivery
  (e.g. with `pandoc`, or a Python markdown-to-PDF library).

## Cost Per Scan (Approximate)

The AI visibility check makes 3 small API calls to Claude per scan.
At current pricing this is roughly $0.01-0.03 per scan — trivial at
low volume, worth monitoring at scale.
