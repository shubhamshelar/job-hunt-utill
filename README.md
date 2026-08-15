# job-hunt-util

Scrapes job postings from LinkedIn, Indeed, and Google, filters out what you've already seen, enriches the results (tech stack, required experience, company relevance), and gives you a localhost web UI to browse it all. No database, no scheduler — just CSV files, run whenever you want.

## What you get

- **Web UI** at http://127.0.0.1:8000 — the main way to use the tool
- Scrape on demand (last 24 hours or 7 days) straight from the UI
- Recent postings ranked first everywhere: dashboard, jobs, companies, tech
- Required experience shown clearly: colored level chip on every row + minimum years in the detail view
- Deterministic enrichment — no LLM/API calls, everything is computed from the data

## Quick start

### 1. Install

```bash
conda create -n jobspy python=3.12 -y && conda activate jobspy
pip install -r requirements.txt
```

### 2. Set your search criteria

Edit `config.py` — job titles, locations, sites, and results per search:

```python
TITLES = ["Software Engineer", "Python Developer", "Backend Engineer"]
LOCATIONS = ["Pune, India", "Mumbai, India"]
SITES = ["linkedin", "indeed", "google"]
RESULTS_PER_SEARCH = 20
```

(You can also change all of this later from the UI's Settings screen — Save rewrites `config.py`.)

### 3. Start the UI

```bash
./run.sh ui          # then open http://127.0.0.1:8000
```

### 4. Scrape and browse

Hit **Scrape 24h** (or **Scrape 7d**) on the dashboard and watch the live log. New jobs flow into the Jobs list automatically — no terminal needed.

## The web UI

- **Dashboard** — total/new counts, per-site split, top companies and techs ranked by recent postings (with "last 7d" badges), and the Scrape / Enrich buttons with a live log drawer.
- **Jobs** — newest first. Filter by search title, location, site, company, tech, experience, remote, date range, or free text. Click a row for the full description, recruiter emails, apply links, and the required experience (e.g. "Senior · 5+ yrs").
- **Companies** — ranked by recent postings (default), closest to your searches, total postings, or new jobs; shows how often each company appears per search title.
- **Tech** — ranked by recent postings (default), total jobs, or new jobs; per-tech counts, experience-level distribution, top companies.
- **Settings** — add/remove search titles, locations, and sites (Save rewrites `config.py`); Cleanup: pick a number of weeks and delete older postings.

"Recent" always means posted within 7 days of the freshest posting in your catalog — so the ranking works no matter how often you scrape.

## How it works

1. **Scrape** — every `TITLES × LOCATIONS` pair is searched on each site via [python-jobspy](https://github.com/dsbowen/python-jobspy); raw results are saved per run.
2. **Dedupe** — every job URL you've ever seen lives in `seen_jobs.csv`; only unseen jobs pass through as "new".
3. **Enrich** — the full history is analyzed deterministically: tech stack, experience level + minimum years, company size, and how relevant each company is to your searches. One row per unique job in `catalog.csv`.
4. **Clean** — prune postings older than N weeks; jobs purged from the seen log can reappear as new if re-scraped.

## The command line (optional)

The UI is a thin wrapper over `run.sh` — the commands are there if you prefer headless runs:

| Command | Description |
|---------|-------------|
| `./run.sh ui` | Start the web UI at http://127.0.0.1:8000 |
| `./run.sh restart` | Stop any UI on port 8000, then start it fresh |
| `./run.sh 24h` | Full pipeline: scrape last 24 hours → filter new → enrich |
| `./run.sh 7d` | Same, for the last 7 days |
| `./run.sh enrich` | Rebuild `catalog.csv` + `adjacency.csv` from raw history |
| `./run.sh clean <weeks>` | Delete postings older than N weeks, purge the seen log, rebuild catalog |
| `./run.sh view [file]` | Pretty-print a jobs CSV |

## Files

```
data/
├── raw/                      # Raw scraped CSVs (full history)
├── output/                   # Filtered new jobs per run
├── catalog.csv               # Derived: one enriched row per unique job
├── adjacency.csv             # Derived: company × search-title relevance
└── seen_jobs.csv             # Persistent log of all seen job URLs
```

`catalog.csv` and `adjacency.csv` are derived artifacts — rebuilt by enrichment, never edited by hand.

## Notes

- Glassdoor (no India support) and ZipRecruiter (persistent blocks) are excluded from scraping
- LinkedIn is scraped directly from its guest jobs API — one combined search per city (capped at `RESULTS_PER_SEARCH × number of titles`), so pagination reaches postings that per-title searches miss. Descriptions, direct apply links, and company details are fetched in parallel only for jobs you haven't seen; descriptions stay empty when LinkedIn login-walls the request
- Jobs without a posting date are dropped; duplicate URLs are removed

## Requirements

- Python 3.12
- conda (recommended) or pip
- See `requirements.txt` for dependencies

# TODO

create issues 
1) improving ranking of jobs by including user profiile from ui 
2) use playright mcp /cli and test ui and find gaps and create detailed issue (this is issue to create more issues)
3) work on infra to bundle it better and host it in future possibly , accounting end user usability, also database may be required for each use so create plan in that direction, we will check scope later on.

## License

MIT
