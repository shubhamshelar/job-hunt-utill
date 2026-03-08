#!/usr/bin/env python3
"""
Job scraper - scrapes jobs from configured sites.
Accepts --hours argument (24 or 168).
Saves output to data/raw/jobs_{hours}h_{timestamp}.csv
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from jobspy import scrape_jobs
import pandas as pd

import config


# ─── Helper Functions ─────────────────────────────────────
def format_elapsed(seconds):
    """Format seconds into minutes and seconds."""
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}m {secs}s"


def get_project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


def ensure_directories():
    """Create data/raw directory if it doesn't exist."""
    raw_dir = get_project_root() / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


# ─── Main Scraping Function ─────────────────────────────────
def scrape_all(hours_old):
    """Scrape jobs for all configured titles and locations."""
    # Get config values
    titles = config.TITLES
    locations = config.LOCATIONS
    sites = config.SITES.copy()  # Don't modify original
    results_per_search = config.RESULTS_PER_SEARCH

    # Remove Glassdoor silently (no India support)
    if "glassdoor" in sites:
        sites.remove("glassdoor")

    all_jobs = []
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    global_start = time.time()

    total = len(titles) * len(locations)
    count = 0

    print(f"\n{'=' * 60}")
    print(f"  Scraping jobs (last {hours_old} hours)")
    print(f"  Titles    : {len(titles)}")
    print(f"  Locations : {len(locations)}")
    print(f"  Sites     : {', '.join(sites)}")
    print(f"{'=' * 60}\n")

    for title in titles:
        for location in locations:
            count += 1
            elapsed = format_elapsed(time.time() - global_start)
            print(f"[{count}/{total}] ⏱ {elapsed} | Scraping: '{title}' in {location} ...")
            step_start = time.time()
            try:
                jobs = scrape_jobs(
                    site_name=sites,
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
        before_date = len(df)
        df = df.dropna(subset=["date_posted"])
        dropped = before_date - len(df)
        if dropped > 0:
            print(f"✓ Removed {dropped} jobs with no date_posted")
        df = df.sort_values("date_posted", ascending=False)

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
