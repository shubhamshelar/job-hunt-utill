#!/usr/bin/env python3
"""
Deterministic job-data enrichment.

Reads all data/raw/jobs_*.csv (full scrape history) and computes per unique
job_url: tech_stack (keyword match), experience_level (title + description
rules), company relevance (company x search_title adjacency), company size
bucket, first/last seen dates, and is_new (membership in the latest
jobs_new_*.csv).

Writes data/catalog.csv (one row per unique job_url) and data/adjacency.csv
(one row per company x search_title pair). Read-only over raw/output/seen
files - never mutates them. Re-running produces byte-identical output.
"""

import csv
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Keyword libraries ─────────────────────────────────────
TECH_KEYWORDS = {
    "Python": [r"\bpython\b", r"\bdjango\b", r"\bflask\b", r"\bfastapi\b"],
    "Java": [r"\bjava\b", r"\bspring(?: ?boot)?\b", r"\bhibernate\b", r"\bj2ee\b"],
    "JavaScript": [
        r"\bjavascript\b", r"\btypescript\b", r"\bnode\.?js\b", r"\breact(?:\.?js)?\b",
        r"\bvue(?:\.?js)?\b", r"\bangular(?:\.?js)?\b", r"\bnext\.?js\b",
    ],
    ".NET": [r"\.net\b", r"\basp\.net\b", r"\bc#(?!\w)"],
    "C++": [r"\bc\+\+(?!\w)"],
    "Go": [r"\bgolang\b", r"\bgo developer\b", r"\bgo engineer\b"],
    "SQL": [r"\bsql\b", r"\bpostgres(?:ql)?\b", r"\bmysql\b", r"\boracle\b"],
    "NoSQL": [r"\bmongodb\b", r"\bredis\b", r"\bdynamodb\b", r"\bcassandra\b", r"\belasticsearch\b"],
    "AWS": [r"\baws\b", r"\bec2\b", r"\bs3\b", r"\blambda\b", r"\bamazon web services\b"],
    "Azure": [r"\bazure\b"],
    "GCP": [r"\bgcp\b", r"\bgoogle cloud\b", r"\bbigquery\b"],
    "Docker": [r"\bdocker\b"],
    "Kubernetes": [r"\bkubernetes\b", r"\bk8s\b"],
    "Terraform": [r"\bterraform\b"],
    "Jenkins": [r"\bjenkins\b"],
    "Kafka": [r"\bkafka\b"],
    "Spark": [r"\bspark\b", r"\bpyspark\b", r"\bdatabricks\b"],
    "Machine Learning": [
        r"\bmachine learning\b", r"\bdeep learning\b", r"\btensorflow\b", r"\bpytorch\b", r"\bml\b",
    ],
    "AI/LLM": [
        r"\bai\b", r"\bartificial intelligence\b", r"\bllm\b", r"\blarge language model\b",
        r"\bgpt\b", r"\brag\b", r"\bgenai\b", r"\bgenerative ai\b",
    ],
}

TECH_PATTERNS = {
    name: [re.compile(p, re.IGNORECASE) for p in patterns]
    for name, patterns in TECH_KEYWORDS.items()
}

# ─── Experience-level rules (first match wins) ─────────────
TITLE_LEVELS = [
    (re.compile(r"\bintern\b|\btrainee\b|\binternship\b"), "intern"),
    (re.compile(r"\bfreshers?\b|\bentry[- ]?level\b|\bgraduate\b|\bget\b|\bcampus\b"), "entry"),
    (re.compile(r"\bjunior\b|\bjr\b|\bassociate\b"), "junior"),
    (re.compile(r"\blead\b|\bprincipal\b|\bstaff\b|\barchitect\b|\bmanager\b|\bhead of\b|\bvp\b|\bvice[- ]?president\b|\bdirector\b"), "lead"),
    (re.compile(r"\bsenior\b|\bsr\b"), "senior"),
    (re.compile(r"\bsde[- ]?3\b|\bsde[- ]?iii\b|\bengineer\s+iii\b"), "senior"),
    (re.compile(r"\bsde[- ]?2\b|\bsde[- ]?ii\b|\bengineer\s+ii\b"), "mid"),
    (re.compile(r"\bsde[- ]?1\b|\bsde[- ]?i\b|\bengineer\s+i\b"), "junior"),
    (re.compile(r"\bmid\b"), "mid"),
]

# Years-of-experience patterns; the (?!...educat) guard excludes
# "15 years full time education" (educational qualification, not experience)
RANGE_RE = re.compile(r"(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs)\b(?!\s*(?:full[ -]?time)?\s*educat)")
MIN_RE = re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs)\b(?!\s*(?:full[ -]?time)?\s*educat)")
BARE_RE = re.compile(r"(\d{1,2})\s+(?:years?|yrs)\b(?!\s*(?:full[ -]?time)?\s*educat)")
ENTRY_RE = re.compile(r"\bfreshers?\b|\bfresh graduate\b|\bentry[- ]?level\b")

FILE_RE = re.compile(r"jobs_\d+h_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})\.csv")


# ─── Helper Functions ─────────────────────────────────────
def get_project_root():
    return Path(__file__).parent.parent


def strip_backslashes(value):
    """CSV escapechar leaves doubled backslashes in text; remove all runs."""
    if pd.isna(value):
        return ""
    return re.sub(r"\\+", "", str(value))


def detect_techs(text):
    found = [name for name, patterns in TECH_PATTERNS.items() if any(p.search(text) for p in patterns)]
    return "|".join(sorted(found))


def years_to_level(years):
    if years < 2:
        return "entry"
    if years < 4:
        return "junior"
    if years < 7:
        return "mid"
    return "senior"


def detect_years(title, desc):
    """Minimum years required as an int-string, or '' if unknown."""
    text = f"{title} {desc}".lower()
    m = RANGE_RE.search(text)
    if m:
        return str(int(m.group(1)))
    m = MIN_RE.search(text)
    if m:
        return str(int(m.group(1)))
    m = BARE_RE.search(text)
    if m:
        return str(int(m.group(1)))
    return ""


def detect_level(title, desc):
    title_lower = str(title).lower()
    for pattern, level in TITLE_LEVELS:
        if pattern.search(title_lower):
            return level
    years = detect_years(title, desc)
    if years:
        return years_to_level(int(years))
    if ENTRY_RE.search(f"{title} {desc}".lower()):
        return "entry"
    return ""


def parse_size(value):
    if pd.isna(value):
        return "unknown"
    s = str(value).strip()
    m = re.fullmatch(r"([\d,]+)\+", s)
    if m:
        return m.group(1).replace(",", "") + "+"
    m = re.fullmatch(r"([\d,]+) to ([\d,]+)", s)
    if m:
        return f"{m.group(1).replace(',', '')}-{m.group(2).replace(',', '')}"
    return "unknown"


def join_emails(value):
    if pd.isna(value):
        return ""
    parts = [p.strip() for p in re.split(r"[,;]", str(value)) if p.strip() and p.strip().lower() != "nan"]
    return "|".join(parts)


def mode_value(values):
    """Most frequent value; ties broken alphabetically. Returns '' if empty."""
    vals = [v for v in values if v and v != "nan" and v != "unknown"]
    if not vals:
        return ""
    return min(vals, key=lambda v: (-vals.count(v), v))


# ─── Main Enrichment Function ──────────────────────────────
def enrich():
    root = get_project_root()
    raw_dir = root / "data" / "raw"
    output_dir = root / "data" / "output"

    if not raw_dir.exists():
        print(f"❌ Error: {raw_dir} not found.")
        sys.exit(1)

    raw_files = sorted(raw_dir.glob("jobs_*.csv"))

    catalog_cols = [
        "job_url", "id", "site", "title", "company", "location", "date_posted",
        "search_title", "search_location", "is_remote", "job_type", "emails",
        "company_industry", "company_url", "company_num_employees",
        "company_size_bucket", "description", "tech_stack", "experience_level",
        "experience_years",
        "company_relevance", "company_total", "company_rank", "first_seen",
        "last_seen", "is_new",
    ]
    adj_cols = [
        "company", "search_title", "count", "company_total", "company_rank",
        "top_size_bucket", "top_industry", "top_techs",
    ]

    if not raw_files:
        print(f"\n{'=' * 60}")
        print("  Enriching job data (deterministic)")
        print(f"  Raw files: 0")
        print(f"{'=' * 60}\n")
        print("⚠ No raw CSV files found in data/raw/ — writing empty catalog.")
        pd.DataFrame(columns=catalog_cols).to_csv(
            root / "data" / "catalog.csv",
            quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False,
        )
        pd.DataFrame(columns=adj_cols).to_csv(
            root / "data" / "adjacency.csv",
            quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False,
        )
        print("✅ Catalog: data/catalog.csv (0 jobs)")
        print("✅ Adjacency: data/adjacency.csv (0 company x title pairs)\n")
        return

    print(f"\n{'=' * 60}")
    print(f"  Enriching job data (deterministic)")
    print(f"  Raw files: {len(raw_files)}")
    print(f"{'=' * 60}\n")

    # ── Load all raw files, tag each row with its scrape date ──
    frames = []
    for p in raw_files:
        m = FILE_RE.match(p.name)
        file_date = (
            m.group(1)[:10]
            if m
            else datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
        )
        df = pd.read_csv(p, escapechar="\\")
        df["_file_date"] = file_date
        df["_file"] = p.name
        frames.append(df)
    allrows = pd.concat(frames, ignore_index=True)
    total_rows = len(allrows)
    print(f"  Loaded {total_rows} rows across {len(raw_files)} files")

    # ── First-seen snapshot: one row per unique job_url ──
    allrows = allrows.sort_values(["_file_date", "_file"], kind="stable")
    first = allrows.drop_duplicates(subset=["job_url"], keep="first").copy()
    last_seen = allrows.groupby("job_url")["_file_date"].max()
    first["first_seen"] = first["_file_date"]
    first["last_seen"] = first["job_url"].map(last_seen)
    print(f"  Unique jobs (by job_url): {len(first)}")

    # Backfill empty descriptions from the latest snapshot that has one
    # (e.g. LinkedIn rows scraped before linkedin_fetch_description was enabled)
    has_desc = allrows["description"].notna() & (allrows["description"].astype(str).str.strip() != "")
    latest_desc = (
        allrows[has_desc]
        .drop_duplicates(subset=["job_url"], keep="last")
        .set_index("job_url")["description"]
    )
    first["description"] = first["description"].where(
        first["description"].notna() & (first["description"].astype(str).str.strip() != ""),
        first["job_url"].map(latest_desc),
    )

    # ── Company x search_title adjacency ──
    pairs = allrows[["job_url", "company", "search_title"]].drop_duplicates()
    adj = pairs.groupby(["company", "search_title"]).size().rename("count").reset_index()
    company_total = pairs.groupby("company").size()
    adj["company_total"] = adj["company"].map(company_total).astype(int)
    rank_order = sorted(company_total.items(), key=lambda kv: (-kv[1], kv[0]))
    rank_map = {company: i + 1 for i, (company, _) in enumerate(rank_order)}
    adj["company_rank"] = adj["company"].map(rank_map).astype(int)

    # ── Enrich catalog rows ──
    first["description"] = first["description"].apply(strip_backslashes)
    first["emails"] = first["emails"].apply(join_emails)
    first["is_remote"] = (first["is_remote"].astype(str).str.lower() == "true").astype(int)
    first["company_size_bucket"] = first["company_num_employees"].apply(parse_size)

    match_text = (first["title"].fillna("").astype(str) + " " + first["description"]).str.lower()
    first["tech_stack"] = match_text.apply(detect_techs)
    first["experience_level"] = first.apply(
        lambda r: detect_level(r["title"], str(r["description"]).lower()), axis=1
    )
    first["experience_years"] = first.apply(
        lambda r: detect_years(r["title"], r["description"]), axis=1
    )

    rel = adj.set_index(["company", "search_title"])["count"]
    first["company_relevance"] = first.apply(
        lambda r: int(rel.get((r["company"], r["search_title"]), 0)), axis=1
    )
    ct = adj.drop_duplicates("company").set_index("company")[["company_total", "company_rank"]]
    first["company_total"] = first["company"].map(ct["company_total"]).fillna(0).astype(int)
    first["company_rank"] = first["company"].map(ct["company_rank"]).fillna(0).astype(int)

    # ── is_new: membership in latest jobs_new_*.csv ──
    new_urls = set()
    out_files = sorted(output_dir.glob("jobs_new_*.csv"), key=lambda p: p.stat().st_mtime)
    if out_files:
        latest_out = pd.read_csv(out_files[-1], usecols=["job_url"])
        new_urls = set(latest_out["job_url"].dropna())
        print(f"  Latest output file: {out_files[-1].name} ({len(new_urls)} new jobs)")
    first["is_new"] = first["job_url"].isin(new_urls).astype(int)

    # ── Per-company stats for adjacency ──
    company_stats = {}
    for company, grp in first.groupby("company"):
        size_mode = mode_value(grp["company_size_bucket"])
        industry_mode = mode_value(grp["company_industry"].dropna().astype(str))
        techs = []
        for ts in grp["tech_stack"]:
            techs += [t for t in str(ts).split("|") if t]
        tech_counts = Counter(techs)
        top_techs = sorted(tech_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        company_stats[company] = (size_mode, industry_mode, "|".join(t for t, _ in top_techs))

    adj["top_size_bucket"] = adj["company"].map(lambda c: company_stats[c][0])
    adj["top_industry"] = adj["company"].map(lambda c: company_stats[c][1])
    adj["top_techs"] = adj["company"].map(lambda c: company_stats[c][2])

    # ── Write catalog.csv ──
    catalog = first[catalog_cols].copy()
    for col in ["job_type", "company_industry", "company_num_employees", "date_posted"]:
        catalog[col] = catalog[col].fillna("")
    catalog = catalog.sort_values(["date_posted", "job_url"], ascending=[False, True])
    catalog_path = root / "data" / "catalog.csv"
    catalog.to_csv(catalog_path, quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False)

    # ── Write adjacency.csv ──
    adjacency = adj[adj_cols].sort_values(["company_rank", "company", "count"], ascending=[True, True, False])
    adj_path = root / "data" / "adjacency.csv"
    adjacency.to_csv(adj_path, quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False)

    # ── Summary ──
    new_count = int(catalog["is_new"].sum())
    with_tech = int((catalog["tech_stack"] != "").sum())
    with_level = int((catalog["experience_level"] != "").sum())
    print(f"\n✅ Catalog: {catalog_path} ({len(catalog)} jobs)")
    print(f"✅ Adjacency: {adj_path} ({len(adjacency)} company x title pairs)")
    print(f"   New jobs (is_new=1): {new_count}")
    print(f"   Jobs with tech_stack: {with_tech}")
    print(f"   Jobs with experience_level: {with_level}")
    print(f"   Jobs with experience_years: {int((catalog['experience_years'] != '').sum())}")
    top_techs_all = Counter()
    for ts in catalog["tech_stack"]:
        top_techs_all.update(t for t in str(ts).split("|") if t)
    print(f"   Top techs: {', '.join(f'{t} ({c})' for t, c in top_techs_all.most_common(10))}")
    print(f"\n📊 Summary: {total_rows} rows → {len(first)} unique jobs\n")


# ─── CLI Entry Point ──────────────────────────────────────
def main():
    enrich()


if __name__ == "__main__":
    main()
