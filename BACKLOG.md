# v2 Backlog

- Site Scan currently fetches raw HTML only (urllib), so JS-heavy/SPA sites under-score on Search Foundations (meta/H1/nav appear missing even if JS-rendered). Fix: headless browser rendering (e.g. Playwright) before parsing. Low priority - rare for actual target market (small/local businesses with server-rendered sites).
- "Other" category: AI Discovery shows as flat 0 instead of "not evaluated" - consider clearer copy distinguishing "scored zero" from "not assessed."
