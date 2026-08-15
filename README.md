# job-hunt-util

A minimal CLI wrapper around the [python-jobspy](https://github.com/dsbowen/python-jobspy) library for scraping job postings from LinkedIn, Indeed, and Google — plus a localhost web UI for browsing and filtering what you've collected.

## 🖼️ Big Picture

**What this tool does:**

1. **Scrapes jobs** from multiple job sites (LinkedIn, Indeed, Google)
2. **Filters duplicates** by tracking already-seen jobs in a persistent log
3. **Saves only new jobs** to CSV output
4. **Enriches deterministically** — no LLM/API: tech stack, experience level + minimum years required, company size, and company relevance to your searches, computed from the data itself
5. **Browses everything** in a localhost web UI (dashboard, filterable job list, company and tech rankings)

**Why use it:**
- No database required — just CSV files
- No scheduler/cron — you run it when you want
- Tracks what you've already seen so you don't get duplicates
- See which companies post most for *your* searches, and which technologies/experience levels they ask for

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Create conda environment (recommended)
conda create -n jobspy python=3.12 -y
conda activate jobspy

# Install dependencies
pip install -r requirements.txt

# Or if you already have the environment
pip install csvkit==2.2.0 python-jobspy==1.1.82 fastapi==0.115.12 uvicorn==0.34.2 jinja2==3.1.5
```

### 2. Configure Your Search

Edit `config.py` to set your search criteria:

```python
# Job titles to search for
TITLES = [
    "Software Engineer",
    "Python Developer",
    "Backend Engineer",
]

# Locations to search
LOCATIONS = [
    "Pune, India",
    "Mumbai, India",
]

# Sites to scrape
SITES = ["linkedin", "indeed", "google"]

# Results per search
RESULTS_PER_SEARCH = 20
```

### 3. Run the Scraper

```bash
# Scrape last 24 hours → filter → output new jobs
./run.sh 24h

# OR scrape last 7 days
./run.sh 7d
```

---

## 📖 Usage Guide

### Available Commands

| Command | Description |
|---------|-------------|
| `./run.sh 24h` | Scrape last 24 hours, filter unseen, save new jobs, rebuild catalog |
| `./run.sh 7d` | Scrape last 7 days, filter unseen, save new jobs, rebuild catalog |
| `./run.sh seen` | Build/update the seen jobs log (no scraping) |
| `./run.sh filter` | Filter latest raw CSV for unseen jobs |
| `./run.sh enrich` | Rebuild `data/catalog.csv` + `data/adjacency.csv` from full raw history |
| `./run.sh clean <weeks>` | Delete raw/output CSVs older than N weeks, purge the seen log to the remaining window, rebuild the catalog |
| `./run.sh ui` | Start the web UI at http://127.0.0.1:8000 |
| `./run.sh restart` | Stop any UI running on port 8000, then start it fresh |
| `./run.sh view` | View latest output with csvcut + csvlook |
| `./run.sh view <filename>` | View specific CSV file |

### Web UI

```bash
./run.sh ui     # then open http://127.0.0.1:8000
```

- **Dashboard** — new/total job counts, per-site split, top companies and techs ranked by recent postings (with "N last 7d" badges), and buttons to **Scrape 24h / Scrape 7d / Enrich** with a live log drawer (no more terminal).
- **Jobs** — filter by search title, location, site, company, tech, experience level, remote, date range, or free text; click a row for the full description, recruiter emails, apply links, relevance counts, and the required experience (level + minimum years, e.g. "Senior · 5+ yrs").
- **Companies** — ranked by recent postings (default), relevance to your searches (how often a company appears for each title you search), total postings, or new jobs.
- **Tech** — ranked by recent postings (default), total jobs, or new jobs; per-tech counts, experience-level distribution, top companies.
- **Settings** — view and edit your search criteria (add/remove titles, locations, sites; results per search) — Save rewrites `config.py` and applies to the next scrape. Also **Cleanup**: pick a number of weeks and delete older posts (raw + output CSVs), purge the seen log to the remaining window (purged jobs can reappear as NEW), and rebuild the catalog.
- Everything is derived from your local CSVs — the UI never writes them; its only actions are the scrape/enrich/clean commands above, run as background subprocesses of `run.sh` (plus the config save).

### Example Workflows

#### First Run (no seen jobs yet)
```bash
# Build empty seen log
./run.sh seen

# Scrape and get all jobs as "new"
./run.sh 24h
```

#### Subsequent Runs
```bash
# Just get truly new jobs since last run
./run.sh 24h
# OR
./run.sh 7d
```

#### View Results
```bash
# View latest output
./run.sh view

# View specific file
./run.sh view jobs_new_2026-03-08_15-47.csv

# Or use csvcut directly
csvcut -c location,job_url,company,title data/output/jobs_new_*.csv | csvlook | less -S
```

---

## 📂 Output Files

After running, you'll find:

```
data/
├── raw/                      # Raw scraped CSVs (full history)
│   └── jobs_24h_2026-03-08_14-30.csv
├── output/                   # Filtered new jobs
│   └── jobs_new_2026-03-08_14-35.csv
├── catalog.csv               # Derived: one row per unique job (enriched)
├── adjacency.csv             # Derived: company × search-title relevance
└── seen_jobs.csv             # Persistent log of all seen URLs
```

`catalog.csv` and `adjacency.csv` are rebuilt by `enrich_jobs.py` (or `./run.sh enrich`) from the full raw history — deterministic, no LLM/API. Full column documentation lives in `.claude/csv-structure.md`.

---

## 🔧 Customization

### Change Search Parameters

Edit `config.py`:
- `TITLES` — Add/remove job titles
- `LOCATIONS` — Add/remove locations
- `SITES` — Choose which sites to scrape (linkedin, indeed, google)
- `RESULTS_PER_SEARCH` — How many results per title/location

### Notes
- Glassdoor is automatically excluded (no India support)
- Jobs with missing `date_posted` are automatically dropped
- Duplicate job URLs are removed
- LinkedIn descriptions are fetched per posting (`linkedin_fetch_description=True`) — makes LinkedIn scrapes slower, but descriptions are silently empty when LinkedIn login-walls the request

---

## ⚠️ Requirements

- Python 3.12
- conda (recommended) or pip
- See `requirements.txt` for dependencies

---

## 📝 License

MIT
