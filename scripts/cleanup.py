#!/usr/bin/env python3
"""
Prune scrape history older than N weeks.

Deletes data/raw/jobs_*.csv and data/output/jobs_new_*.csv whose scrape
timestamp (from the filename, falling back to mtime) is older than the
cutoff. Then rewrites data/seen_jobs.csv to the job_urls present in the
remaining raw window, so purged jobs can reappear as NEW if re-scraped.

Run enrich afterwards to rebuild the catalog for the smaller window
(run.sh `clean` chains both).
"""

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

RAW_TS_RE = re.compile(r"jobs_\d+h_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})\.csv")
OUT_TS_RE = re.compile(r"jobs_new_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})\.csv")
TS_FMT = "%Y-%m-%d_%H-%M"


def get_project_root():
    return Path(__file__).parent.parent


def file_timestamp(path, pattern):
    m = pattern.match(path.name)
    if m:
        return datetime.strptime(m.group(1), TS_FMT)
    return datetime.fromtimestamp(path.stat().st_mtime)


def cleanup(weeks):
    root = get_project_root()
    raw_dir = root / "data" / "raw"
    output_dir = root / "data" / "output"
    seen_file = root / "data" / "seen_jobs.csv"
    cutoff = datetime.now() - timedelta(weeks=weeks)

    print(f"\n{'=' * 60}")
    print(f"  Cleaning posts older than {weeks} week(s)")
    print(f"  Cutoff: {cutoff.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}\n")

    deleted_raw = []
    deleted_out = []
    if raw_dir.exists():
        for p in sorted(raw_dir.glob("jobs_*.csv")):
            if file_timestamp(p, RAW_TS_RE) < cutoff:
                deleted_raw.append(p)
    if output_dir.exists():
        for p in sorted(output_dir.glob("jobs_new_*.csv")):
            if file_timestamp(p, OUT_TS_RE) < cutoff:
                deleted_out.append(p)

    for p in deleted_raw:
        print(f"  🗑 raw:     {p.name}")
        p.unlink()
    for p in deleted_out:
        print(f"  🗑 output:  {p.name}")
        p.unlink()
    if not deleted_raw and not deleted_out:
        print("  Nothing to delete — all files are within the window.\n")

    # ── Purge seen log to the remaining raw window ──
    seen_before = 0
    if seen_file.exists():
        seen_before = len(pd.read_csv(seen_file, usecols=["job_url"]))

    remaining_urls = set()
    if raw_dir.exists():
        for p in sorted(raw_dir.glob("jobs_*.csv")):
            df = pd.read_csv(p, usecols=["job_url"])
            remaining_urls.update(df["job_url"].dropna().unique().tolist())

    pd.DataFrame({"job_url": sorted(remaining_urls)}).to_csv(seen_file, index=False)
    seen_after = len(remaining_urls)
    print(f"  Seen log: {seen_before} → {seen_after} URLs (remaining window)")

    print(f"\n✅ Deleted {len(deleted_raw)} raw + {len(deleted_out)} output file(s).")
    print("   Next: enrich rebuilds the catalog for the remaining window.\n")


def main():
    parser = argparse.ArgumentParser(description="Prune scrape history older than N weeks.")
    parser.add_argument("--weeks", type=int, required=True, help="Delete files older than this many weeks (1-52)")
    args = parser.parse_args()
    if not 1 <= args.weeks <= 52:
        parser.error("--weeks must be between 1 and 52")
    cleanup(args.weeks)


if __name__ == "__main__":
    main()
