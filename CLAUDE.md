# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

@.claude/architecture.md
@.claude/commands.md
@.claude/csv-structure.md

## Rules

- `config.py` holds the user's personal job-search settings. The UI Settings screen (`POST /api/config`) and direct editing are the sanctioned ways to change `TITLES`/`LOCATIONS`/`SITES`/`RESULTS_PER_SEARCH`; never change them unprompted.
- `data/` is gitignored runtime state — never commit it or hand-edit the CSVs.
- Any new CSV output must use `quoting=csv.QUOTE_NONNUMERIC, escapechar="\\"` so `build_seen.py`/`filter_unseen.py` can read it back with pandas.
- Keep `scripts/` a flat set of standalone scripts: resolve the project root from `__file__` (not CWD) and import `config` via the existing `sys.path` insert; don't restructure into a package without being asked.
- Preserve `run.sh`'s pipeline ordering (build_seen → scraper → filter_unseen) when editing the workflow.
- Don't run `./run.sh 24h`, `7d`, or `clean` unprompted — scraping hits external job sites and takes minutes per run; cleaning deletes data.
- Only `scripts/enrich_jobs.py` writes `data/catalog.csv` / `data/adjacency.csv` — they are derived artifacts, never hand-edited.
- The web UI (`webapp/`) must never write CSVs or re-implement pipeline steps — it shells out to `run.sh` for any pipeline action. Exception: the Settings screen rewrites `config.py` via `POST /api/config` (never CSVs).
- `scripts/cleanup.py` (via `run.sh clean <weeks>` or the UI Cleanup button) is the only sanctioned way to prune `data/raw`/`data/output` and shrink `seen_jobs.csv` — it rewrites seen to the URLs of the remaining raw window. `build_seen.py`'s merge semantics stay untouched.
- Enrichment is deterministic (keyword/regex data analysis) — no LLM/API calls in the analysis layer.
- Scraped descriptions contain doubled backslashes (`8\\-10 years`) from the CSV `escapechar` — normalize with `re.sub(r"\\+", "", text)` before any regex (see csv-structure.md).
