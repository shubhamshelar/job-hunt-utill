#!/usr/bin/env python3
"""
Build seen jobs log - combines all raw CSVs + existing seen log.
Saves deduplicated job_url list to data/seen_jobs.csv
"""

import sys
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


def get_seen_file():
    """Get the seen_jobs.csv file path."""
    return get_project_root() / "data" / "seen_jobs.csv"


def ensure_data_dir():
    """Create data directory if it doesn't exist."""
    data_dir = get_project_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


# ─── Main Build Seen Function ─────────────────────────────
def build_seen():
    """Build seen_jobs.csv from all raw CSVs + existing seen log."""
    raw_dir = get_raw_dir()
    seen_file = get_seen_file()
    
    print(f"\n{'=' * 60}")
    print("  Building seen jobs log")
    print(f"{'=' * 60}\n")

    # Collect all URLs from sources
    all_urls = []
    sources_info = []

    # 1. Scan data/raw/ for jobs_*.csv files
    if raw_dir.exists():
        csv_files = sorted(raw_dir.glob("jobs_*.csv"))
        if csv_files:
            raw_urls = set()
            for csv_file in csv_files:
                try:
                    df = pd.read_csv(csv_file)
                    if "job_url" in df.columns:
                        urls = df["job_url"].dropna().unique().tolist()
                        raw_urls.update(urls)
                        sources_info.append((csv_file.name, len(urls)))
                except Exception as e:
                    print(f"  ⚠ Error reading {csv_file.name}: {e}")
            
            all_urls.extend(list(raw_urls))
            print(f"  📂 Found {len(raw_urls)} URLs in {len(csv_files)} raw CSV(s)")
        else:
            print(f"  📂 No raw CSV files found in {raw_dir}")
    else:
        print(f"  📂 Raw directory doesn't exist yet: {raw_dir}")

    # 2. Load existing seen_jobs.csv if it exists (merge, don't overwrite)
    if seen_file.exists():
        try:
            seen_df = pd.read_csv(seen_file)
            if "job_url" in seen_df.columns:
                existing_urls = seen_df["job_url"].dropna().unique().tolist()
                all_urls.extend(existing_urls)
                sources_info.append(("seen_jobs.csv", len(existing_urls)))
                print(f"  📂 Found {len(existing_urls)} URLs in existing seen_jobs.csv")
        except Exception as e:
            print(f"  ⚠ Error reading seen_jobs.csv: {e}")

    # Deduplicate
    unique_urls = list(set(all_urls))
    print(f"\n  Total unique URLs: {len(unique_urls)}")

    # Print source breakdown
    if sources_info:
        print("\n  Source breakdown:")
        for source, count in sources_info:
            print(f"    - {source}: {count} URLs")
        print(f"    - Total after dedup: {len(unique_urls)} URLs")

    # Save only job_url column
    ensure_data_dir()
    result_df = pd.DataFrame({"job_url": unique_urls})
    result_df.to_csv(seen_file, index=False)

    print(f"\n✅ Saved {len(unique_urls)} seen job URLs to: {seen_file}")
    
    return seen_file


# ─── CLI Entry Point ──────────────────────────────────────
def main():
    build_seen()


if __name__ == "__main__":
    main()
