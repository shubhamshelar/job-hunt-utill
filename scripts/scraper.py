#!/usr/bin/env python3
"""
Job scraper - scrapes jobs from configured sites.
Accepts --hours argument (24 or 168).
Saves output to data/raw/jobs_{hours}h_{timestamp}.csv

LinkedIn is scraped directly from the guest jobs API (one OR-combined search
per location, all titles at once, cap = RESULTS_PER_SEARCH x len(TITLES)) so
pagination reaches into the long tail instead of re-fetching the same page-1
cards per title. Job detail pages (description, direct apply URL, emails,
company industry/logo) are fetched afterwards in parallel, only for URLs not
in seen_jobs.csv. Indeed/Google go through jobspy as before.

Direct LinkedIn scraping also sidesteps jobspy's stale card parser
(jobspy 1.1.82 looks for `time.job-search-card__listdate`; LinkedIn renamed
the class to `--new` in 2026, so jobspy returned None dates and the rows
were silently dropped by the no-date filter).
"""

import argparse
import csv
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from jobspy import scrape_jobs
from jobspy.linkedin.constant import headers as LINKEDIN_HEADERS
from jobspy.linkedin.util import parse_company_industry
from jobspy.util import extract_emails_from_text, markdown_converter, remove_attributes
import pandas as pd
import requests
from bs4 import BeautifulSoup

import config


DETAIL_WORKERS = 6
DETAIL_TIMEOUT = 5
# Guest API login-walls on sustained bursts (~2+ req/s got walled after ~30
# requests in testing; ~1 req/s recovered 100%). Throttle globally to ~1.1/s.
DETAIL_MIN_INTERVAL = 0.9
LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"

_rate_lock = threading.Lock()
_rate_last = [0.0]


def _throttle():
    with _rate_lock:
        wait = DETAIL_MIN_INTERVAL - (time.time() - _rate_last[0])
        if wait > 0:
            time.sleep(wait)
        _rate_last[0] = time.time()

# Raw CSV schema (jobspy-compatible; enrich/filter_unseen depend on it)
RAW_COLUMNS = [
    "id", "site", "job_url", "job_url_direct", "title", "company", "location",
    "date_posted", "job_type", "salary_source", "interval", "min_amount",
    "max_amount", "currency", "is_remote", "job_level", "job_function",
    "listing_type", "emails", "description", "company_industry", "company_url",
    "company_logo", "company_url_direct", "company_addresses",
    "company_num_employees", "company_revenue", "company_description", "skills",
    "experience_range", "company_rating", "company_reviews_count",
    "vacancy_count", "work_from_home_type", "search_title", "search_location",
]

_thread_local = threading.local()


def _thread_session():
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update(LINKEDIN_HEADERS)
    return _thread_local.session


# ─── Helper Functions ─────────────────────────────────────
def format_elapsed(seconds):
    """Format seconds into minutes and seconds."""
    m, secs = divmod(int(seconds), 60)
    return f"{m}m {secs}s"


def get_project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


def ensure_directories():
    """Create data/raw directory if it doesn't exist."""
    raw_dir = get_project_root() / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


def load_seen_urls():
    """Read data/seen_jobs.csv into a set; empty set if missing/corrupt."""
    path = get_project_root() / "data" / "seen_jobs.csv"
    if not path.exists():
        return set()
    try:
        return set(pd.read_csv(path)["job_url"].dropna())
    except Exception:
        return set()


def load_undescribed_urls():
    """job_urls whose catalog description is still empty (fetch was
    login-walled) — these are retried on every scrape."""
    path = get_project_root() / "data" / "catalog.csv"
    if not path.exists():
        return set()
    try:
        cat = pd.read_csv(path, usecols=["job_url", "description"])
        empty = cat["description"].isna() | (
            cat["description"].astype(str).str.strip() == ""
        )
        return set(cat.loc[empty, "job_url"])
    except Exception:
        return set()


def is_remote(title, description, location):
    """Match jobspy's is_job_remote heuristic (title + description + location)."""
    desc = description if isinstance(description, str) else ""
    full = f"{title} {desc} {location}".lower()
    return any(k in full for k in ("remote", "work from home", "wfh"))


def parse_listdate(time_tag):
    """Date from the card's <time> tag: datetime attr, else relative text."""
    if time_tag is not None:
        if time_tag.get("datetime"):
            try:
                return datetime.strptime(time_tag["datetime"], "%Y-%m-%d").strftime("%Y-%m-%d")
            except Exception:
                pass
        text = time_tag.get_text(strip=True)
        match = re.match(r"(\d+)\s+(hour|day|week|month)s?\s+ago", text)
        if match:
            n, unit = int(match.group(1)), match.group(2)
            days = {"hour": n / 24, "day": n, "week": n * 7, "month": n * 30}[unit]
            return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return None


def linkedin_search(keywords, location, hours_old, results_wanted):
    """
    Paginate the LinkedIn guest jobs API for one (keyword, location) query.
    Returns a list of row dicts using the raw-CSV schema (details fetched
    separately). Stops at results_wanted, an empty page, or the 1000-offset cap.
    """
    rows = []
    seen_ids = set()
    start = 0
    session = _thread_session()
    params = {"keywords": keywords, "location": location, "f_TPR": f"r{hours_old * 3600}"}
    while len(rows) < results_wanted and start < 1000:
        params["start"] = start
        try:
            response = session.get(LINKEDIN_SEARCH_URL, params=params, timeout=10)
            if response.status_code == 429:
                print("  ⚠ LinkedIn 429 (rate limited) — stopping this search")
                break
            response.raise_for_status()
        except Exception as e:
            print(f"  ⚠ LinkedIn search error (start={start}): {e}")
            break

        cards = BeautifulSoup(response.text, "html.parser").find_all(
            "div", class_="base-search-card"
        )
        if not cards:
            break

        for card in cards:
            if len(rows) >= results_wanted:
                break
            href_tag = card.find("a", class_="base-card__full-link")
            if href_tag is None or "href" not in href_tag.attrs:
                continue
            job_id = href_tag["href"].split("?")[0].split("-")[-1]
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title_tag = card.find("span", class_="sr-only")
            title = title_tag.get_text(strip=True) if title_tag else "N/A"

            company_tag = card.find("h4", class_="base-search-card__subtitle")
            company_a = company_tag.find("a") if company_tag else None
            company = company_a.get_text(strip=True) if company_a else "N/A"
            company_url = ""
            if company_a is not None and company_a.has_attr("href"):
                company_url = urlunparse(urlparse(company_a["href"])._replace(query=""))

            loc = "N/A"
            metadata = card.find("div", class_="base-search-card__metadata")
            if metadata is not None:
                loc_tag = metadata.find("span", class_="job-search-card__location")
                if loc_tag is not None:
                    loc = loc_tag.get_text(strip=True)

            time_tag = card.find("time", class_="job-search-card__listdate") or card.find(
                "time", class_="job-search-card__listdate--new"
            )
            rows.append({
                "id": f"li-{job_id}",
                "site": "linkedin",
                "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "title": title,
                "company": company,
                "location": loc,
                "date_posted": parse_listdate(time_tag),
                "company_url": company_url,
            })
        time.sleep(random.uniform(2.5, 4.0))
        start += 10
    return rows


def fetch_linkedin_detail(job_url):
    """
    GET one LinkedIn job page; parse description (markdown), direct apply
    URL, emails, company industry/logo. Returns {} on any failure
    (login-wall, timeout, ...). Mirrors jobspy's own output formats.
    """
    try:
        _throttle()
        response = _thread_session().get(job_url, timeout=DETAIL_TIMEOUT)
        response.raise_for_status()
        if "linkedin.com/signup" in response.url:
            return {}
    except Exception:
        return {}

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        div = soup.find(
            "div", class_=lambda x: x and "show-more-less-html__markup" in x
        )
        description = None
        if div is not None:
            description = markdown_converter(
                remove_attributes(div).prettify(formatter="html")
            )

        job_url_direct = None
        apply_code = soup.find("code", id="applyUrl")
        if apply_code:
            match = re.search(r'(?<=\?url=)[^"]+', apply_code.decode_contents().strip())
            if match:
                job_url_direct = unquote(match.group())

        emails = ",".join(extract_emails_from_text(description)) if description else None

        company_logo = None
        logo_img = soup.find("img", {"class": "artdeco-entity-image"})
        if logo_img is not None:
            company_logo = logo_img.get("data-delayed-url")

        return {
            "description": description,
            "job_url_direct": job_url_direct,
            "emails": emails or None,
            "company_industry": parse_company_industry(soup),
            "company_logo": company_logo,
        }
    except Exception:
        return {}


def fetch_details_parallel(job_urls):
    """
    Fetch LinkedIn detail pages concurrently (globally rate-limited), then
    retry login-walled misses once after a cooldown. Returns
    {job_url: {field: value}}.
    """
    details = {}
    if not job_urls:
        return details
    print(f"\n  Fetching details for {len(job_urls)} LinkedIn job(s) "
          f"({DETAIL_WORKERS} workers, ~1 req/s) ...")
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        futures = {executor.submit(fetch_linkedin_detail, url): url for url in job_urls}
        done = 0
        for future in as_completed(futures):
            done += 1
            details[futures[future]] = future.result()
            if done % 20 == 0 or done == len(job_urls):
                print(f"  {done}/{len(job_urls)} fetched")

    missed = [u for u in job_urls if not (details.get(u) or {}).get("description")]
    if missed:
        print(f"  {len(missed)} without description (login-wall?) — "
              f"retrying after 20s cooldown ...")
        time.sleep(20)
        recovered = 0
        for i, url in enumerate(missed, 1):
            result = fetch_linkedin_detail(url)
            if result.get("description"):
                details[url] = result
                recovered += 1
            if i % 25 == 0 or i == len(missed):
                print(f"  retry {i}/{len(missed)}  ({recovered} recovered)")
    return details


def tag_search_title(row_title, titles):
    """Map a LinkedIn OR-search row back to the first matching config title."""
    t = str(row_title).lower()
    for title in titles:
        if title.lower() in t:
            return title
    return "Other"


# ─── Main Scraping Function ─────────────────────────────────
def scrape_all(hours_old):
    """Scrape jobs for all configured titles and locations."""
    titles = config.TITLES
    locations = config.LOCATIONS
    sites = [s for s in config.SITES if s not in ("glassdoor", "zip_recruiter")]
    results_per_search = config.RESULTS_PER_SEARCH

    # LinkedIn: one OR-combined search per location, cap scaled by title count
    linkedin_cap = results_per_search * len(titles)
    or_term = " OR ".join(titles)
    other_sites = [s for s in sites if s != "linkedin"]

    all_jobs = []
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    global_start = time.time()
    total = (len(locations) * (1 if "linkedin" in sites else 0)
             + len(locations) * len(titles) * (1 if other_sites else 0))

    print(f"\n{'=' * 60}")
    print(f"  Scraping jobs (last {hours_old} hours)")
    print(f"  Titles    : {len(titles)}")
    print(f"  Locations : {len(locations)}")
    print(f"  Sites     : {', '.join(sites)}")
    if "linkedin" in sites:
        print(f"  LinkedIn  : direct guest API, OR search per location, cap {linkedin_cap}")
    print(f"{'=' * 60}\n")

    count = 0
    for location in locations:
        if "linkedin" in sites:
            count += 1
            elapsed = format_elapsed(time.time() - global_start)
            print(f"[{count}/{total}] ⏱ {elapsed} | Scraping: LinkedIn OR "
                  f"({len(titles)} titles) in {location} ...")
            step_start = time.time()
            rows = linkedin_search(or_term, location, hours_old, linkedin_cap)
            if rows:
                df = pd.DataFrame(rows, columns=RAW_COLUMNS)
                df["search_title"] = df["title"].apply(
                    lambda t: tag_search_title(t, titles))
                df["search_location"] = location
                all_jobs.append(df)
            step_time = format_elapsed(time.time() - step_start)
            if rows:
                print(f"  ✓ Found {len(rows)} jobs  ({step_time})")
            else:
                print(f"  ✗ No jobs found  ({step_time})")

        if not other_sites:
            continue
        for title in titles:
            count += 1
            elapsed = format_elapsed(time.time() - global_start)
            print(f"[{count}/{total}] ⏱ {elapsed} | Scraping: '{title}' in {location} ...")
            step_start = time.time()
            try:
                jobs = scrape_jobs(
                    site_name=other_sites,
                    search_term=title,
                    google_search_term=f"{title} jobs in {location} last {hours_old} hours",
                    location=location,
                    results_wanted=results_per_search,
                    hours_old=hours_old,
                    country_indeed="India",
                    verbose=0,
                )
                step_time = format_elapsed(time.time() - step_start)
                if jobs is not None and len(jobs) > 0:
                    jobs["search_title"] = title
                    jobs["search_location"] = location
                    all_jobs.append(jobs)
                    print(f"  ✓ Found {len(jobs)} jobs  ({step_time})")
                else:
                    print(f"  ✗ No jobs found  ({step_time})")
            except Exception as e:
                step_time = format_elapsed(time.time() - step_start)
                print(f"  ✗ Error: {e}  ({step_time})")

    if not all_jobs:
        print("\nNo jobs found across all searches.")
        return None

    df = pd.concat(all_jobs, ignore_index=True)

    # Remove duplicates by job_url
    before = len(df)
    df = df.drop_duplicates(subset=["job_url"], keep="first")
    print(f"\n✓ Removed {before - len(df)} duplicate jobs")

    # Remove jobs with no date_posted
    if "date_posted" in df.columns:
        # jobspy returns datetime.date objects for indeed/google; our LinkedIn
        # rows are strings — normalize to ISO strings before sorting/dropping
        df["date_posted"] = pd.to_datetime(
            df["date_posted"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        before_date = len(df)
        df = df.dropna(subset=["date_posted"])
        dropped = before_date - len(df)
        if dropped > 0:
            print(f"✓ Removed {dropped} jobs with no date_posted")
        df = df.sort_values("date_posted", ascending=False)

    # Fetch LinkedIn detail pages: unseen URLs plus seen ones whose catalog
    # description is still empty (previous fetches were login-walled)
    if "linkedin" in sites and len(df):
        li_mask = df["site"] == "linkedin"
        seen = load_seen_urls()
        undescribed = load_undescribed_urls()
        need_mask = li_mask & (
            ~df["job_url"].isin(seen) | df["job_url"].isin(undescribed)
        )
        need = df.loc[need_mask, "job_url"].unique()
        details = fetch_details_parallel(list(need))
        if details:
            for col in ("description", "job_url_direct", "emails",
                        "company_industry", "company_logo"):
                if col in df.columns:
                    df[col] = df[col].astype(object)
            for url, values in details.items():
                for col, val in values.items():
                    if val:
                        df.loc[df["job_url"] == url, col] = val
        df.loc[li_mask, "is_remote"] = (
            df.loc[li_mask].apply(
                lambda r: is_remote(r["title"], r["description"], r["location"]),
                axis=1,
            ).astype(bool)
        )
        df["is_remote"] = df["is_remote"].fillna(False).astype(bool)

    # Save to data/raw/
    raw_dir = ensure_directories()
    csv_filename = f"jobs_{hours_old}h_{timestamp}.csv"
    csv_path = raw_dir / csv_filename
    df.to_csv(csv_path, quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False)

    total_time = format_elapsed(time.time() - global_start)
    print(f"\n✅ CSV saved: {csv_path}")
    print(f"⏱  Total time: {total_time}")
    print(f"📊 Total unique jobs: {len(df)}")
    print(df[["site", "title", "company", "location", "job_type", "date_posted"]].head(10).to_string(index=False))

    return csv_path


# ─── CLI Entry Point ──────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scrape job postings")
    parser.add_argument(
        "--hours",
        type=int,
        required=True,
        choices=[24, 168],
        help="Hours old: 24 (last 24 hours) or 168 (last 7 days)",
    )
    args = parser.parse_args()

    result = scrape_all(args.hours)
    if result:
        print(f"\nOutput: {result}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
