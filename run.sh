#!/bin/bash
#
# job-hunt-util - Single entry point for job scraping workflow
#
# Usage:
#   ./run.sh 24h    → build_seen → scraper --hours 24 → filter_unseen → enrich
#   ./run.sh 7d     → build_seen → scraper --hours 168 → filter_unseen → enrich
#   ./run.sh seen   → build_seen only
#   ./run.sh filter → filter_unseen only (on latest raw CSV)
#   ./run.sh enrich → rebuild catalog + adjacency only
#   ./run.sh clean N → delete raw/output CSVs older than N weeks, purge seen, enrich
#   ./run.sh ui     → start web UI
#   ./run.sh restart → kill anything on port 8000, then start the web UI
#

set -e  # Stop immediately if any script fails

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Get Python executable from conda environment
# Resolve the env's interpreter path (running bare `python` prints only to stderr)
if command -v conda &> /dev/null; then
    PYTHON_CMD="$(conda run -n jobspy which python 2>/dev/null)" || PYTHON_CMD="python"
else
    PYTHON_CMD="python"
fi

# Track start time
START_TIME=$(date +%s)

# Function to print usage
usage() {
    echo "Usage: $0 {24h|7d|seen|filter|view|enrich|clean|ui|restart} [filename|weeks]"
    echo ""
    echo "Options:"
    echo "  24h         - Scrape last 24 hours, filter unseen jobs"
    echo "  7d          - Scrape last 7 days, filter unseen jobs"
    echo "  seen        - Build/update seen jobs log only"
    echo "  filter      - Filter unseen jobs from latest raw CSV"
    echo "  view        - View jobs in CSV with csvcut + csvlook"
    echo "               Usage: $0 view jobs_new_2026-03-08_15-47.csv"
    echo "               Or:    $0 view (uses latest in data/output/)"
    echo "  enrich      - Rebuild data/catalog.csv and data/adjacency.csv"
    echo "  clean       - Delete raw/output CSVs older than N weeks, purge seen"
    echo "               log to the remaining window, rebuild catalog"
    echo "               Usage: $0 clean 8"
    echo "  ui          - Start the web UI at http://127.0.0.1:8000"
    echo "  restart     - Stop any UI running on port 8000, then start it fresh"
    exit 1
}

# Function to run a Python script
run_script() {
    local script_path="$1"
    shift
    echo ""
    echo "────────────────────────────────────────────────────────"
    echo "▶ Running: $script_path $@"
    echo "────────────────────────────────────────────────────────"
    $PYTHON_CMD "$script_path" "$@"
}

# Parse command
case "${1:-}" in
    24h)
        echo "========================================================"
        echo "  Job Hunt Util - Last 24 Hours"
        echo "========================================================"
        run_script "scripts/build_seen.py"
        run_script "scripts/scraper.py" --hours 24
        run_script "scripts/filter_unseen.py"
        run_script "scripts/enrich_jobs.py"
        ;;
    7d)
        echo "========================================================"
        echo "  Job Hunt Util - Last 7 Days"
        echo "========================================================"
        run_script "scripts/build_seen.py"
        run_script "scripts/scraper.py" --hours 168
        run_script "scripts/filter_unseen.py"
        run_script "scripts/enrich_jobs.py"
        ;;
    seen)
        echo "========================================================"
        echo "  Job Hunt Util - Build Seen Jobs Log"
        echo "========================================================"
        run_script "scripts/build_seen.py"
        ;;
    filter)
        echo "========================================================"
        echo "  Job Hunt Util - Filter Unseen Jobs"
        echo "========================================================"
        run_script "scripts/filter_unseen.py"
        ;;
    enrich)
        echo "========================================================"
        echo "  Job Hunt Util - Rebuild Catalog"
        echo "========================================================"
        run_script "scripts/enrich_jobs.py"
        ;;
    clean)
        WEEKS="${2:?Usage: ./run.sh clean <weeks>  (e.g. clean 8)}"
        echo "========================================================"
        echo "  Job Hunt Util - Clean posts older than $WEEKS week(s)"
        echo "========================================================"
        run_script "scripts/cleanup.py" --weeks "$WEEKS"
        run_script "scripts/enrich_jobs.py"
        ;;
    ui)
        echo "========================================================"
        echo "  Job Hunt Util - Web UI"
        echo "  http://127.0.0.1:8000  (Ctrl+C to stop)"
        echo "========================================================"
        $PYTHON_CMD -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
        ;;
    restart)
        echo "========================================================"
        echo "  Job Hunt Util - Restart Web UI"
        echo "========================================================"
        # Kill whatever is listening on port 8000 (our own uvicorn), wait for it to free
        UI_PIDS=$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null || true)
        if [ -n "$UI_PIDS" ]; then
            echo "Stopping existing UI on port 8000 (PID: $UI_PIDS)"
            kill $UI_PIDS 2>/dev/null || true
            for _ in 1 2 3 4 5; do
                lsof -tiTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 || break
                sleep 1
            done
        fi
        if lsof -tiTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
            echo "❌ Port 8000 is still in use by something else:"
            lsof -nP -iTCP:8000 -sTCP:LISTEN
            exit 1
        fi
        echo "  Starting fresh at http://127.0.0.1:8000  (Ctrl+C to stop)"
        $PYTHON_CMD -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
        ;;
    view)
        # Find the CSV file to view
        if [ -n "${2:-}" ]; then
            # User provided filename
            CSV_FILE="$2"
            # If it's a relative path, prepend data/output/
            if [[ "$CSV_FILE" != /* ]] && [[ "$CSV_FILE" != data/* ]]; then
                CSV_FILE="data/output/$CSV_FILE"
            fi
        else
            # Find latest in data/output/
            OUTPUT_DIR="$SCRIPT_DIR/data/output"
            if [ -d "$OUTPUT_DIR" ]; then
                CSV_FILE=$(ls -t "$OUTPUT_DIR"/jobs_new_*.csv 2>/dev/null | head -1)
            fi
            if [ -z "$CSV_FILE" ]; then
                echo "❌ Error: No CSV files found in data/output/"
                echo "   Run './run.sh 24h' or './run.sh 7d' first.\n"
                exit 1
            fi
        fi

        # Check file exists
        if [ ! -f "$CSV_FILE" ]; then
            echo "❌ Error: File not found: $CSV_FILE\n"
            exit 1
        fi

        echo "========================================================"
        echo "  Viewing: $(basename "$CSV_FILE")"
        echo "========================================================"
        echo ""
        csvcut -c location,job_url,company,title "$CSV_FILE" | csvlook | less -S
        ;;
    *)
        usage
        ;;
esac

# Calculate total elapsed time
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
MINS=$((ELAPSED / 60))
SECS=$((ELAPSED % 60))

echo ""
echo "========================================================"
echo "  ✅ Complete! Total time: ${MINS}m ${SECS}s"
echo "========================================================"
