# CSV Structure & Data Facts

Ground truth for the CSV files under `data/` (gitignored runtime state). Verified 2026-03-15 by reading the 15 raw + 15 output files and `seen_jobs.csv` with pandas in the `jobspy` conda env.

## Files

| File | Produced by | Shape | Contents |
|---|---|---|---|
| `data/raw/jobs_{hours}h_{ts}.csv` | `scripts/scraper.py` | one per scrape run (24h/168h) | all scraped postings, deduped by `job_url`, rows missing `date_posted` dropped |
| `data/output/jobs_new_{ts}.csv` | `scripts/filter_unseen.py` | one per run | raw minus seen_jobs.csv URLs |
| `data/seen_jobs.csv` | `build_seen.py` + `filter_unseen.py` | grows | single column: `job_url` |
| `data/catalog.csv` | `scripts/enrich_jobs.py` | one row per unique `job_url` | first-seen snapshot (empty `description` and `job_url_direct` backfilled from the latest snapshot that has one) + deterministic enrichment |
| `data/adjacency.csv` | `scripts/enrich_jobs.py` | one row per (company, search_title) | company × search-title relevance |

History at time of writing: 15 raw files = 3698 rows = 2343 unique `job_url`s (matches seen_jobs.csv). Sites: indeed 2694 / linkedin 964 / google 40 / zip_recruiter 0.

## Scraped CSV columns (raw + output share this schema)

| Column | dtype (pandas read-back) | Null % (varies per file) | Meaning / sample values |
|---|---|---|---|
| `id` | str | 0% | per-site posting id, e.g. `in-b1439d8bcaa6898a` |
| `site` | str | 0% | `indeed` / `linkedin` / `google` |
| `job_url` | str | 0% | canonical listing URL — the dedup key everywhere, e.g. `https://in.indeed.com/viewjob?jk=...` |
| `job_url_direct` | str | 19–33% | direct company ATS link when known |
| `title` | str | 0% | e.g. `Senior Consultant \| Backend Developer - Java \|...` |
| `company` | str | 0% | e.g. `Amazon.com`, `ITAakash Strategic Software Pvt Ltd` |
| `location` | str | 0% | job location, e.g. `Pune, Maharashtra` |
| `date_posted` | str `YYYY-MM-DD` | 0% (rows missing it are dropped) | posting date as ISO string, e.g. `2026-03-14` |
| `job_type` | str | 39–43% | `fulltime` / `internship` |
| `salary_source`, `interval`, `min_amount`, `max_amount`, `currency` | float | **100%** | never populated by jobspy for these India searches |
| `is_remote` | bool | 0% | `True`/`False` — 93% False in practice |
| `job_level`, `job_function` | float | **100%** | never populated |
| `listing_type` | float | 100% | never populated |
| `emails` | str | 93–96% | recruiter/apply email(s) when present |
| `description` | str | 19–33% (per file) | full posting text; avg ~3700 chars when present. See escaping gotcha below. |
| `company_industry` | str | 56–71% | e.g. `Internet And Software` |
| `company_url` | str | 0% | e.g. `https://in.indeed.com/cmp/Deloitte` |
| `company_logo` | str | 41–44% | cloudfront square logo URL |
| `company_url_direct` | str | 41–44% | company website |
| `company_addresses` | str | 44–45% | HQ address(es) — often US-based, not the job's city |
| `company_num_employees` | str | 44–45% | exact value set: `10,000+`, `5,001 to 10,000`, `1,001 to 5,000`, `501 to 1,000`, `201 to 500`, `51 to 200`, `11 to 50`, `2 to 10`, `Decline to state` |
| `company_revenue` | str | 45–49% | e.g. `more than $10B (USD)`, `$100M to $500M (USD)` |
| `company_description` | str | 48–49% | short blurb, ~160 chars |
| `skills` | float | **100%** | column exists in jobspy output but is never filled — filled by `enrich_jobs.py` instead (as `tech_stack` in catalog) |
| `experience_range` | float | **100%** | same — see `experience_level` in catalog |
| `company_rating`, `company_reviews_count`, `vacancy_count`, `work_from_home_type` | float | 100% | never populated |
| `search_title` | str | 0% | which config.py title produced this row (provenance) |
| `search_location` | str | 0% | which config.py location produced this row |

## Escaping gotcha (critical for any regex work)

All CSVs are written with `quoting=csv.QUOTE_NONNUMERIC, escapechar="\\"`. csv.writer escapes **every** source backslash as `\\`, so text on disk contains doubled backslashes: `8\\-10 years`, `\\+`, `\\&`, `\\#`. 98% of non-null descriptions contain at least one backslash run.

- `pd.read_csv(path)` (default) reads them back literally — `8\\-10 years` (two chars).
- `pd.read_csv(path, escapechar="\\")` additionally unescapes quoted commas/quotes — use this when reading for display/matching.
- **Before any regex**: normalize with `re.sub(r"\\+", "", text)` (then `.lower()`). After this, `8\-10 years` → `8-10 years` and all patterns can be written plainly.
- `build_seen.py`/`filter_unseen.py` are unaffected: they only touch `job_url`.

## Derived facts (verified)

- **Site skew**: indeed 73% of history, linkedin 26%, google ~1%, zip_recruiter 0. Treat indeed as the primary source.
- **Company skew**: top 10 by postings — Amazon.com 286, Capgemini 196, Accenture 148, Microsoft 134, JPMorganChase 109, Citi 89, Apple 70, MetLife 64, Barclays 61, Wipro 54. 713 unique companies total.
- **Company × search_title cross-tab is the relevance signal**: e.g. Amazon.com 200× "Software Engineer", Turing 27× "Python Developer", Capgemini 21× "Backend Engineer". A company posting many jobs for a searched title = "close to what you searched".
- **Seniority in titles**: senior/junior/intern tokens are common (6/19/2 in a 61-row sample); explicit "X years" appears in only ~12% of descriptions → experience must combine title tokens + description regexes (see enrich_jobs.py precedence table).
- **Experience detection (upgraded 2026-08-15)**: `experience_level` ∈ intern/entry/junior/mid/senior/lead (title tokens: intern, fresher, graduate/GET/campus, junior/jr/associate, lead/principal/staff/architect/manager/vp/vice president/director, senior/sr, SDE-1/2/3, Engineer I/II/III, mid; then years regexes in title+description). New catalog column `experience_years` = minimum years as int-string or `""`, from range lower bound / `N+` / bare `N years` (`yrs` suffix supported), with a guard excluding the "N years full time education" qualification boilerplate (SAP/Capgemini-style postings). Coverage after upgrade: 340/513 rows with a level, 217/513 with years (previously 273). `0` years maps to `entry`.
- **LinkedIn (direct API scrape, since 2026-08-15)**: `scraper.py` scrapes LinkedIn itself from the guest jobs API instead of jobspy — one OR-combined search per location (cap `RESULTS_PER_SEARCH × len(TITLES)`), then fetches detail pages in parallel (6 workers, globally throttled to ~1 req/s — bursts trigger login-walls) for unseen URLs plus seen URLs whose catalog description is still empty, with one retry pass after a 20s cooldown. Fills `description` (markdown, like jobspy's), `job_url_direct` (from the page's `code#applyUrl` — often absent), `emails`, `company_industry`, `company_logo`. Guest-page descriptions silently stay empty when LinkedIn login-walls. Jobspy's card parser broke when LinkedIn renamed `time.job-search-card__listdate` → `--new` (jobspy 1.1.82 returned None dates; the no-date filter dropped every LinkedIn row); our parser uses the new class plus a relative-date ("19 hours ago") fallback. Before 2026-08-15, LinkedIn went through jobspy with `linkedin_fetch_description=True` (sequential per-job GETs) and 100% of older LinkedIn rows have empty descriptions (Indeed ~100% coverage via embedded JSON).
- **Tech keywords** appear reliably in descriptions (Python 9, Java 12, AWS 11, AI 9 in a 61-row sample) — keyword matching on title+description works well.

## Future ideas (backlog)

- **LLM ranking/summarization** (later phase — catalog schema is forward-compatible; just add columns): score fit against a profile, summarize descriptions, draft cover letters. Keep deterministic columns as the base.
- **Salary enrichment**: jobspy salary fields are 100% null for India — external sources (levels.fyi, ambitionbox, glassdoor) could fill `min_amount`/`max_amount` per company.
- **Cross-site dedup quality**: same job posted on indeed + linkedin has different URLs — company+title+location fuzzy matching could merge them.
- **Alerts**: desktop/email notification when `is_new` count is high or a target company posts.
- **Scheduler mode**: auto-scrape daily (cron) instead of manual/UI trigger.
- **Application tracking**: statuses (saved/applied/rejected) + notes in a local annotations CSV (user declined for v1 — revisit).
- **Company insights**: aggregate salary/tech/level trends per company from catalog history.
