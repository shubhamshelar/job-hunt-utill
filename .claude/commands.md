# Setup & Commands

There is no build, linter, or test suite.

## Environment

```bash
conda create -n jobspy python=3.12 -y && conda activate jobspy
pip install -r requirements.txt   # csvkit, python-jobspy, fastapi, uvicorn, jinja2
```

`run.sh` resolves the jobspy env's interpreter via `conda run -n jobspy which python`, falling back to plain `python` when conda is missing.

## Entry point: run.sh

```bash
./run.sh 24h        # full pipeline: build_seen → scraper --hours 24 → filter_unseen → enrich
./run.sh 7d         # same, --hours 168
./run.sh seen       # rebuild data/seen_jobs.csv only
./run.sh filter     # filter latest raw CSV only (fails if seen_jobs.csv missing)
./run.sh enrich     # rebuild data/catalog.csv + data/adjacency.csv from full raw history
./run.sh clean N    # delete raw/output CSVs older than N weeks, purge seen log to the
                    # remaining window, rebuild catalog  (N required, 1-52)
./run.sh view [f]   # pretty-print latest (or named) data/output/*.csv via csvkit
./run.sh ui         # start the web UI at http://127.0.0.1:8000
./run.sh restart    # kill whatever is on port 8000, then start the UI fresh
```

`view` accepts a bare filename (resolved under `data/output/`) or a path starting with `data/` or `/`.

## Direct script invocation

Scripts can be run directly but must resolve correctly regardless of CWD (they anchor to `__file__`, see architecture notes):

```bash
python scripts/scraper.py --hours 24        # --hours required, choices=[24, 168]
python scripts/build_seen.py
python scripts/filter_unseen.py [raw.csv]   # optional arg; defaults to latest raw CSV by mtime
python scripts/enrich_jobs.py               # deterministic; byte-identical output on rerun
python scripts/cleanup.py --weeks 8         # --weeks required, 1-52; deletes + purges seen
```

Timestamps in filenames use `%Y-%m-%d_%H-%M` throughout.

## Web UI

```bash
./run.sh ui        # uvicorn webapp.app:app on 127.0.0.1:8000 (Ctrl+C to stop)
```

- Screens: **Dashboard** (stats, top companies/techs with "N last 7d" counts, run buttons + live log), **Jobs** (filters: search title, location, site, company, tech, experience, remote, date range, free-text; detail modal with description/emails/links + experience level and minimum years), **Companies** (ranked by recent postings [default], relevance to searches, jobs, or new-jobs; per-search-title counts), **Tech** (ranked by recent postings [default], jobs, or new-jobs; per-tech counts, experience distribution, top companies), **Settings** (add/remove search titles, locations, sites; results per search; Save rewrites config.py; Cleanup: enter weeks → delete old posts + purge seen log + rebuild catalog, with confirm).
- The UI never writes CSVs. Its pipeline actions are **Scrape 24h / Scrape 7d / Enrich** buttons plus Settings → Cleanup, which spawn `bash run.sh …` as a background subprocess and stream the log over SSE (`GET /api/runs/{id}/stream`). The Settings screen's Save button rewrites `config.py` via `POST /api/config` (the one sanctioned non-CSV write).
- Single-worker: one run at a time (a second `POST /api/scrape|enrich|clean` while one is active → 409). The finished run's log is only kept until the next run finishes — reconnect the stream while it runs or shortly after.
- Localhost-only, single-user: no auth.
- JSON API endpoints (all GET unless noted): `/api/config`, `/api/summary` (top lists include `recent` = postings within 7 days of the freshest catalog date, ranked recent-first), `/api/filters`, `/api/jobs` (query-param filters, `sort`∈{date_posted,company,title,company_relevance,company_total,first_seen}, drops `description` from list payload), `/api/jobs/{row_id}` (row_id = catalog row index; full row incl. description, experience_level, experience_years), `/api/companies?sort=recent|relevance|jobs|new` (default recent), `/api/tech?sort=recent|jobs|new` (default recent; rows include `recent_count`), `/api/status`, `POST /api/scrape {hours: 24|168}`, `POST /api/enrich`, `POST /api/clean {weeks: 1-52}`, `POST /api/config {titles, locations, sites, results_per_search}`.
