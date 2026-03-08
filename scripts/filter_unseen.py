#!/usr/bin/env python3
"""
Filter unseen jobs - compares latest raw CSV against seen_jobs.csv.
Saves new jobs to data/output/jobs_new_{timestamp}.csv
Appends newly seen URLs to data/seen_jobs.csv
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Helper Functions ─────────────────────────────────────
def get_project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


def get_raw_dir():
    """Get the raw data directory."""
    return get_project_root() / "data" / "raw"


def get_output_dir():
    """Get the output data directory."""
    return get_project_root() / "data" / "output"


def get_seen_file():
    """Get the seen_jobs.csv file path."""
    return get_project_root() / "data" / "seen_jobs.csv"


def ensure_directories():
    """Create data directories if they don't exist."""
    output_dir = get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def find_latest_raw_csv():
    """Find the most recent CSV file in data/raw/"""
    raw_dir = get_raw_dir()
    csv_files = sorted(raw_dir.glob("jobs_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if csv_files:
        return csv_files[0]
    return None


# ─── Main Filter Unseen Function ───────────────────────────
def filter_unseen(csv_path=None):
    """Filter out already-seen jobs from a raw CSV."""
    seen_file = get_seen_file()
    
    # Exit with error if seen_jobs.csv doesn't exist
    if not seen_file.exists():
        print(f"\n❌ Error: {seen_file} not found.")
        print("   Run './run.sh seen' first to build the seen jobs log.\n")
        sys.exit(1)

    # Load seen jobs
    seen_df = pd.read_csv(seen_file)
    seen_urls = set(seen_df["job_url"].dropna().tolist())
    print(f"\n{'=' * 60}")
    print(f"  Filtering unseen jobs")
    print(f"  Seen jobs: {len(seen_urls)}")
    print(f"{'=' * 60}\n")

    # Find CSV to filter
    if csv_path:
        raw_csv = Path(csv_path)
        if not raw_csv.exists():
            print(f"❌ Error: File not found: {raw_csv}")
            sys.exit(1)
    else:
        raw_csv = find_latest_raw_csv()
        if not raw_csv:
            print("❌ Error: No raw CSV files found in data/raw/")
            print("   Run './run.sh 24h' or './run.sh 7d' first to scrape jobs.\n")
            sys.exit(1)

    print(f"  Input: {raw_csv.name}")

    # Load raw jobs
    raw_df = pd.read_csv(raw_csv)
    total_jobs = len(raw_df)
    print(f"  Total jobs in raw CSV: {total_jobs}")

    # Filter out seen jobs
    if "job_url" not in raw_df.columns:
        print("❌ Error: No 'job_url' column found in CSV")
        sys.exit(1)

    unseen_df = raw_df[~raw_df["job_url"].isin(seen_urls)]
    already_seen = total_jobs - len(unseen_df)
    new_jobs = len(unseen_df)

    print(f"  Already seen: {already_seen}")
    print(f"  New jobs: {new_jobs}")

    # Save new jobs to output
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    output_dir = ensure_directories()
    output_filename = f"jobs_new_{timestamp}.csv"
    output_path = output_dir / output_filename

    unseen_df.to_csv(output_path, quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False)
    print(f"\n✅ Saved {new_jobs} new jobs to: {output_path}")

    # Append newly seen URLs to seen_jobs.csv
    new_urls = unseen_df["job_url"].dropna().tolist()
    if new_urls:
        existing_urls = list(seen_urls)
        all_urls = existing_urls + new_urls
        unique_urls = list(set(all_urls))
        
        # Save updated seen_jobs.csv
        result_df = pd.DataFrame({"job_url": unique_urls})
        result_df.to_csv(seen_file, index=False)
        print(f"✅ Updated seen_jobs.csv: {len(unique_urls)} total URLs")

    print(f"\n📊 Summary: {total_jobs} total → {already_seen} seen → {new_jobs} new")
    print(f"   Output: {output_path}\n")
    
    return output_path


# ─── CLI Entry Point ──────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Filter unseen jobs from raw CSV")
    parser.add_argument(
        "csv_file",
        nargs="?",
        help="Path to raw CSV file (optional, auto-detects latest if not provided)",
    )
    args = parser.parse_args()
    
    filter_unseen(args.csv_file)


if __name__ == "__main__":
    main()
