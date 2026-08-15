#!/usr/bin/env python3
"""
FastAPI web UI for the job-hunt catalog.

Read-only over data/: the only pipeline actions are shelling out to run.sh
as background subprocesses (scrape 24h/7d, enrich). Never writes CSVs.
"""

import asyncio
import importlib
import json
import queue
import subprocess
import sys
import threading
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import config

REPO_ROOT = Path(__file__).parent.parent
CATALOG_PATH = REPO_ROOT / "data" / "catalog.csv"
ADJACENCY_PATH = REPO_ROOT / "data" / "adjacency.csv"
OUTPUT_DIR = REPO_ROOT / "data" / "output"
CONFIG_PATH = REPO_ROOT / "config.py"

ALLOWED_SITES = ["linkedin", "indeed", "google"]

CONFIG_TEMPLATE = """# ─── User Configuration ─────────────────────────────────────
# Edit this file to customize your job search
# All other scripts read from this config

# Job titles to search for
TITLES = [
{titles}
]

# Locations to search in
LOCATIONS = [
{locations}
]

# Sites to scrape (linkedin, indeed, google)
# Note: Glassdoor is automatically removed (no India support)
SITES = {sites}

# Number of results to fetch per title/location combination
RESULTS_PER_SEARCH = {results}

# ──────────────────────────────────────────────────────────
"""

app = FastAPI(title="job-hunt-util UI")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

SORT_WHITELIST = {"date_posted", "company", "title", "company_relevance", "company_total", "first_seen"}


# ─── Catalog cache (re-read only when mtime changes) ──────
_catalog_lock = threading.Lock()
_catalog = None
_catalog_mtime = None


def load_catalog():
    global _catalog, _catalog_mtime
    if not CATALOG_PATH.exists():
        return None
    mtime = CATALOG_PATH.stat().st_mtime
    with _catalog_lock:
        if _catalog is None or mtime != _catalog_mtime:
            _catalog = pd.read_csv(CATALOG_PATH, escapechar="\\")
            # empty strings read back as NaN; keep them empty for matching/display
            _catalog["tech_stack"] = _catalog["tech_stack"].fillna("")
            _catalog["experience_level"] = _catalog["experience_level"].fillna("")
            if "experience_years" in _catalog.columns:
                # QUOTE_NONNUMERIC stores bare ints unquoted → column reads back
                # as float; coerce to int-as-str so the API emits "7", not 7.0
                _catalog["experience_years"] = (
                    pd.to_numeric(_catalog["experience_years"], errors="coerce")
                    .astype("Int64")
                    .astype(str)
                    .replace("<NA>", "")
                )
            _catalog_mtime = mtime
    return _catalog


def recent_mask(cat):
    """Boolean mask: rows posted within 7 days of the freshest date_posted."""
    d = pd.to_datetime(cat["date_posted"], errors="coerce")
    return d >= (d.max() - pd.Timedelta(days=7))


def invalidate_catalog():
    global _catalog, _catalog_mtime
    with _catalog_lock:
        _catalog = None
        _catalog_mtime = None


def load_adjacency():
    if not ADJACENCY_PATH.exists():
        return None
    return pd.read_csv(ADJACENCY_PATH, escapechar="\\")


def to_records(df):
    """DataFrame -> list of JSON-safe dicts (NaN becomes null)."""
    return json.loads(df.to_json(orient="records"))


def split_csv(value):
    return [v.strip() for v in value.split(",") if v.strip()]


# ─── Background run manager ────────────────────────────────
class RunState:
    def __init__(self, kind, cmd, label):
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind
        self.cmd = cmd
        self.label = label
        self.status = "running"
        self.returncode = None
        self.lines = []
        self.queue = queue.Queue()
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.finished_at = None

    def serialize(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_run_lock = threading.Lock()
_current_run = None
_last_run = None


def _worker(run):
    global _current_run, _last_run
    proc = subprocess.Popen(
        run.cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        line = line.rstrip("\n")
        run.lines.append(line)
        if len(run.lines) > 2000:
            run.lines = run.lines[-2000:]
        run.queue.put(("line", line))
    proc.wait()
    run.returncode = proc.returncode
    run.status = "done" if proc.returncode == 0 else "failed"
    run.finished_at = datetime.now().isoformat(timespec="seconds")
    run.queue.put(("done", {"status": run.status, "returncode": run.returncode}))
    with _run_lock:
        _current_run = None
        _last_run = run
    invalidate_catalog()


def start_run(kind, weeks=None):
    global _current_run
    with _run_lock:
        if _current_run is not None:
            return None
        if kind == "scrape_24h":
            run = RunState(kind, ["bash", "run.sh", "24h"], "Scrape 24h (build_seen → scraper → filter → enrich)")
        elif kind == "scrape_7d":
            run = RunState(kind, ["bash", "run.sh", "7d"], "Scrape 7d (build_seen → scraper → filter → enrich)")
        elif kind == "enrich":
            run = RunState(kind, ["bash", "run.sh", "enrich"], "Rebuild catalog")
        elif kind == "clean":
            run = RunState(kind, ["bash", "run.sh", "clean", str(weeks)], f"Clean posts older than {weeks} weeks")
        else:
            raise ValueError(f"unknown run kind: {kind}")
        _current_run = run
    threading.Thread(target=_worker, args=(run,), daemon=True).start()
    return run


def find_run(run_id):
    for run in (_current_run, _last_run):
        if run is not None and run.id == run_id:
            return run
    return None


# ─── Pages ─────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"page": "dashboard"})


@app.get("/jobs", response_class=HTMLResponse)
def page_jobs(request: Request):
    return templates.TemplateResponse(request, "jobs.html", {"page": "jobs"})


@app.get("/companies", response_class=HTMLResponse)
def page_companies(request: Request):
    return templates.TemplateResponse(request, "companies.html", {"page": "companies"})


@app.get("/tech", response_class=HTMLResponse)
def page_tech(request: Request):
    return templates.TemplateResponse(request, "tech.html", {"page": "tech"})


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"page": "settings"})


# ─── Run APIs ──────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    hours: int


@app.post("/api/scrape")
def api_scrape(body: ScrapeRequest):
    if body.hours not in (24, 168):
        raise HTTPException(400, detail={"error": "hours must be 24 or 168"})
    run = start_run("scrape_24h" if body.hours == 24 else "scrape_7d")
    if run is None:
        raise HTTPException(409, detail={"error": "a run is already active"})
    return run.serialize()


@app.post("/api/enrich")
def api_enrich():
    run = start_run("enrich")
    if run is None:
        raise HTTPException(409, detail={"error": "a run is already active"})
    return run.serialize()


class CleanRequest(BaseModel):
    weeks: int


@app.post("/api/clean")
def api_clean(body: CleanRequest):
    if not 1 <= body.weeks <= 52:
        raise HTTPException(400, detail={"error": "weeks must be 1-52"})
    run = start_run("clean", body.weeks)
    if run is None:
        raise HTTPException(409, detail={"error": "a run is already active"})
    return run.serialize()


@app.get("/api/runs/{run_id}/stream")
async def api_run_stream(run_id: str, request: Request):
    run = find_run(run_id)
    if run is None:
        raise HTTPException(404, detail={"error": "unknown run id"})

    async def gen():
        for line in run.lines:
            yield f"event: line\ndata: {json.dumps(line)}\n\n"
        if run.status != "running":
            yield f"event: done\ndata: {json.dumps({'status': run.status, 'returncode': run.returncode})}\n\n"
            return
        while True:
            if await request.is_disconnected():
                break
            try:
                event, payload = await asyncio.to_thread(run.queue.get, timeout=1)
            except queue.Empty:
                continue
            if event == "line":
                yield f"event: line\ndata: {json.dumps(payload)}\n\n"
            else:
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                break

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status")
def api_status():
    cat = load_catalog()
    return {
        "has_catalog": cat is not None,
        "catalog_mtime": datetime.fromtimestamp(CATALOG_PATH.stat().st_mtime).isoformat(timespec="seconds") if cat is not None else None,
        "current_run": _current_run.serialize() if _current_run else None,
        "last_run": _last_run.serialize() if _last_run else None,
    }


# ─── Data APIs ─────────────────────────────────────────────
@app.get("/api/config")
def api_config():
    return {
        "titles": config.TITLES,
        "locations": config.LOCATIONS,
        "sites": config.SITES,
        "results_per_search": config.RESULTS_PER_SEARCH,
        "allowed_sites": ALLOWED_SITES,
    }


class ConfigUpdateRequest(BaseModel):
    titles: list
    locations: list
    sites: list
    results_per_search: int


def _clean_list(values, label):
    if not isinstance(values, list) or not values:
        raise HTTPException(400, detail={"error": f"{label} must be a non-empty list"})
    out = []
    for v in values:
        s = str(v).strip()
        if not s:
            raise HTTPException(400, detail={"error": f"{label} contains an empty value"})
        if len(s) > 100 or "\n" in s or "\r" in s:
            raise HTTPException(400, detail={"error": f"{label} values must be ≤100 chars, no newlines"})
        if s not in out:
            out.append(s)
    return out


@app.post("/api/config")
def api_config_update(body: ConfigUpdateRequest):
    titles = _clean_list(body.titles, "titles")
    locations = _clean_list(body.locations, "locations")
    sites = _clean_list(body.sites, "sites")
    if not set(sites) <= set(ALLOWED_SITES):
        raise HTTPException(400, detail={"error": f"sites must be a subset of {ALLOWED_SITES}"})
    if not 1 <= body.results_per_search <= 100:
        raise HTTPException(400, detail={"error": "results_per_search must be 1-100"})
    text = CONFIG_TEMPLATE.format(
        titles="\n".join(f"    {json.dumps(v)}," for v in titles),
        locations="\n".join(f"    {json.dumps(v)}," for v in locations),
        sites=json.dumps(sites),
        results=body.results_per_search,
    )
    tmp = CONFIG_PATH.with_suffix(".py.tmp")
    tmp.write_text(text)
    tmp.replace(CONFIG_PATH)
    importlib.reload(config)
    return api_config()


@app.get("/api/summary")
def api_summary():
    cat = load_catalog()
    if cat is None:
        raise HTTPException(503, detail={"error": "no catalog yet", "has_catalog": False})
    rm = recent_mask(cat)
    tech_counter = Counter()
    new_tech_counter = Counter()
    recent_tech_counter = Counter()
    for ts, is_new, is_recent in zip(cat["tech_stack"], cat["is_new"], rm):
        for t in str(ts).split("|"):
            if t:
                tech_counter[t] += 1
                if is_new == 1:
                    new_tech_counter[t] += 1
                if is_recent:
                    recent_tech_counter[t] += 1
    recent_by_company = cat[rm].groupby("company").size()
    company_stats = (
        cat.groupby("company")
        .agg(total=("job_url", "size"), new=("is_new", "sum"))
        .sort_values(["total", "company"], ascending=[False, True])
    )
    company_stats["recent"] = recent_by_company.reindex(company_stats.index).fillna(0).astype(int)
    company_stats = company_stats.sort_values(
        ["recent", "total", "company"], ascending=[False, False, True]
    )
    out_files = sorted(OUTPUT_DIR.glob("jobs_new_*.csv"), key=lambda p: p.stat().st_mtime)
    return {
        "total_jobs": len(cat),
        "new_jobs": int(cat["is_new"].sum()),
        "by_site": cat.groupby("site").size().to_dict(),
        "top_companies": [
            {"company": company, "total": int(row["total"]), "new": int(row["new"]),
             "recent": int(row["recent"])}
            for company, row in company_stats.head(8).iterrows()
        ],
        "top_techs": sorted(
            (
                {"tech": t, "count": c, "new_count": new_tech_counter.get(t, 0),
                 "recent": recent_tech_counter.get(t, 0)}
                for t, c in tech_counter.items()
            ),
            key=lambda r: (-r["recent"], -r["count"], r["tech"]),
        )[:10],
        "last_output_file": out_files[-1].name if out_files else None,
        "last_enriched_at": datetime.fromtimestamp(CATALOG_PATH.stat().st_mtime).isoformat(timespec="seconds"),
    }


@app.get("/api/filters")
def api_filters():
    cat = load_catalog()
    if cat is None:
        raise HTTPException(503, detail={"error": "no catalog yet", "has_catalog": False})
    company_order = (
        cat.groupby("company")["company_total"].max()
        .sort_values(ascending=False).index.tolist()
    )
    techs = set()
    for ts in cat["tech_stack"]:
        techs.update(t for t in str(ts).split("|") if t)
    return {
        "search_titles": sorted(cat["search_title"].dropna().unique().tolist()),
        "locations": sorted(cat["location"].dropna().unique().tolist()),
        "sites": sorted(cat["site"].dropna().unique().tolist()),
        "companies": company_order[:100],
        "techs": sorted(techs),
        "experience_levels": sorted(set(cat["experience_level"].dropna().astype(str)) - {""}),
    }


@app.get("/api/jobs")
def api_jobs(
    search_title: str = "", location: str = "", site: str = "", company: str = "",
    tech: str = "", experience: str = "", remote: str = "", new: str = "",
    date_from: str = "", date_to: str = "", q: str = "",
    sort: str = "date_posted", order: str = "desc", limit: int = 50, offset: int = 0,
):
    cat = load_catalog()
    if cat is None:
        raise HTTPException(503, detail={"error": "no catalog yet", "has_catalog": False})
    if sort not in SORT_WHITELIST:
        raise HTTPException(400, detail={"error": f"sort must be one of {sorted(SORT_WHITELIST)}"})
    limit = max(1, min(limit, 200))

    df = cat
    if search_title:
        df = df[df["search_title"].isin(split_csv(search_title))]
    if location:
        df = df[df["location"].isin(split_csv(location))]
    if site:
        df = df[df["site"].isin(split_csv(site))]
    if company:
        df = df[df["company"].isin(split_csv(company))]
    if experience:
        df = df[df["experience_level"].isin(split_csv(experience))]
    if tech:
        want = split_csv(tech)
        df = df[df["tech_stack"].fillna("").str.split("|").apply(lambda xs: any(t in xs for t in want))]
    if remote == "1":
        df = df[df["is_remote"] == 1]
    elif remote == "0":
        df = df[df["is_remote"] == 0]
    if new == "1":
        df = df[df["is_new"] == 1]
    if date_from:
        df = df[df["date_posted"].fillna("") >= date_from]
    if date_to:
        df = df[df["date_posted"].fillna("") <= date_to]
    if q:
        ql = q.lower()
        mask = (
            df["title"].str.lower().str.contains(ql, na=False)
            | df["company"].str.lower().str.contains(ql, na=False)
            | df["description"].fillna("").str.lower().str.contains(ql, na=False)
        )
        df = df[mask]

    df = df.sort_values(sort, ascending=(order == "asc"), kind="stable")
    total = len(df)
    slice_df = df.iloc[offset:offset + limit].drop(columns=["description"])
    items = to_records(slice_df)
    for record, idx in zip(items, slice_df.index):
        record["row_id"] = int(idx)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/api/jobs/{row_id}")
def api_job_detail(row_id: int):
    cat = load_catalog()
    if cat is None:
        raise HTTPException(503, detail={"error": "no catalog yet", "has_catalog": False})
    if row_id < 0 or row_id >= len(cat):
        raise HTTPException(404, detail={"error": "unknown job id"})
    return to_records(cat.iloc[[row_id]])[0]


@app.get("/api/companies")
def api_companies(sort: str = "recent", limit: int = 100):
    cat = load_catalog()
    adj = load_adjacency()
    if cat is None or adj is None:
        raise HTTPException(503, detail={"error": "no catalog yet", "has_catalog": False})
    if sort not in ("relevance", "jobs", "new", "recent"):
        raise HTTPException(400, detail={"error": "sort must be relevance|jobs|new|recent"})

    new_by_company = cat[cat["is_new"] == 1].groupby("company").size()
    recent_by_company = cat[recent_mask(cat)].groupby("company").size()
    job_counts = cat.groupby("company").size()
    comp_meta = (
        adj.groupby("company")
        .agg(
            rank=("company_rank", "min"),
            size_bucket=("top_size_bucket", "first"),
            industry=("top_industry", "first"),
            top_techs=("top_techs", "first"),
        )
        .reset_index()
    )
    comp_meta["total"] = comp_meta["company"].map(job_counts).fillna(0).astype(int)
    comp_meta["new"] = comp_meta["company"].map(new_by_company).fillna(0).astype(int)
    comp_meta["recent"] = comp_meta["company"].map(recent_by_company).fillna(0).astype(int)

    titles_by_company = {}
    for company, grp in adj.groupby("company"):
        titles_by_company[company] = [
            {"search_title": row["search_title"], "count": int(row["count"])}
            for _, row in grp.sort_values("count", ascending=False).iterrows()
        ]
    comp_meta["titles"] = comp_meta["company"].map(titles_by_company)

    if sort == "jobs":
        comp_meta = comp_meta.sort_values(["total", "company"], ascending=[False, True])
    elif sort == "new":
        comp_meta = comp_meta.sort_values(["new", "total", "company"], ascending=[False, False, True])
    elif sort == "recent":
        comp_meta = comp_meta.sort_values(["recent", "total", "company"], ascending=[False, False, True])
    else:
        comp_meta = comp_meta.sort_values(["rank", "company"], ascending=[True, True])

    return to_records(comp_meta.head(limit))


@app.get("/api/tech")
def api_tech(sort: str = "recent"):
    cat = load_catalog()
    if cat is None:
        raise HTTPException(503, detail={"error": "no catalog yet", "has_catalog": False})
    if sort not in ("jobs", "new", "recent"):
        raise HTTPException(400, detail={"error": "sort must be jobs|new|recent"})

    rm = recent_mask(cat)
    rows = []
    for tech in sorted(set(t for ts in cat["tech_stack"] for t in str(ts).split("|") if t)):
        mask = cat["tech_stack"].fillna("").str.split("|").apply(lambda xs: tech in xs)
        subset = cat[mask]
        level_dist = subset["experience_level"].fillna("").value_counts().to_dict()
        top_companies = (
            subset.groupby("company").size()
            .sort_values(ascending=False).head(5).index.tolist()
        )
        rows.append({
            "tech": tech,
            "count": len(subset),
            "new_count": int(subset["is_new"].sum()),
            "recent_count": int(rm[mask].sum()),
            "experience": level_dist,
            "top_companies": top_companies,
        })
    if sort == "new":
        return sorted(rows, key=lambda r: (-r["new_count"], -r["count"], r["tech"]))
    if sort == "recent":
        return sorted(rows, key=lambda r: (-r["recent_count"], -r["count"], r["tech"]))
    return sorted(rows, key=lambda r: (-r["count"], r["tech"]))
