# job-hunt-util

A minimal CLI wrapper around the [python-jobspy](https://github.com/dsbowen/python-jobspy) library for scraping job postings from LinkedIn, Indeed, ZipRecruiter, and Google.

## 🖼️ Big Picture

**What this tool does:**

1. **Scrapes jobs** from multiple job sites (LinkedIn, Indeed, ZipRecruiter, Google)
2. **Filters duplicates** by tracking already-seen jobs in a persistent log
3. **Saves only new jobs** to CSV output
4. **Run manually** whenever you want fresh job listings

**Why use it:**
- No database required — just CSV files
- No scheduler/cron — you run it when you want
- Tracks what you've already seen so you don't get duplicates
- Simple CSV output that's easy to open in Excel or Google Sheets

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
pip install csvkit==2.2.0 python-jobspy==1.1.82
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
SITES = ["linkedin", "indeed", "zip_recruiter", "google"]

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
| `./run.sh 24h` | Scrape last 24 hours, filter unseen, save new jobs |
| `./run.sh 7d` | Scrape last 7 days, filter unseen, save new jobs |
| `./run.sh seen` | Build/update the seen jobs log (no scraping) |
| `./run.sh filter` | Filter latest raw CSV for unseen jobs |
| `./run.sh view` | View latest output with csvcut + csvlook |
| `./run.sh view <filename>` | View specific CSV file |

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
├── raw/                      # Raw scraped CSVs
│   └── jobs_24h_2026-03-08_14-30.csv
├── output/                   # Filtered new jobs
│   └── jobs_new_2026-03-08_14-35.csv
└── seen_jobs.csv             # Persistent log of all seen URLs
```

---

## 🔧 Customization

### Change Search Parameters

Edit `config.py`:
- `TITLES` — Add/remove job titles
- `LOCATIONS` — Add/remove locations
- `SITES` — Choose which sites to scrape (linkedin, indeed, zip_recruiter, google)
- `RESULTS_PER_SEARCH` — How many results per title/location

### Notes
- Glassdoor is automatically excluded (no India support)
- Jobs with missing `date_posted` are automatically dropped
- Duplicate job URLs are removed

---

## ⚠️ Requirements

- Python 3.12
- conda (recommended) or pip
- See `requirements.txt` for dependencies

---

## 📝 License

MIT
