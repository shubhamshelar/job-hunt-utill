#!/bin/bash
#
# job-hunt-util - Single entry point for job scraping workflow
#
# Usage:
#   ./run.sh 24h    → build_seen → scraper --hours 24 → filter_unseen
#   ./run.sh 7d     → build_seen → scraper --hours 168 → filter_unseen
#   ./run.sh seen   → build_seen only
#   ./run.sh filter → filter_unseen only (on latest raw CSV)
#

set -e  # Stop immediately if any script fails

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Get Python executable from conda environment
# Try to find conda with jobspy env, fallback to python
if command -v conda &> /dev/null; then
    PYTHON_CMD="$(conda run -n jobspy python 2>/dev/null)" || PYTHON_CMD="python"
else
    PYTHON_CMD="python"
fi

# Track start time
START_TIME=$(date +%s)

# Function to print usage
usage() {
    echo "Usage: $0 {24h|7d|seen|filter|view} [filename]"
    echo ""
    echo "Options:"
    echo "  24h         - Scrape last 24 hours, filter unseen jobs"
    echo "  7d          - Scrape last 7 days, filter unseen jobs"
    echo "  seen        - Build/update seen jobs log only"
    echo "  filter      - Filter unseen jobs from latest raw CSV"
    echo "  view        - View jobs in CSV with csvcut + csvlook"
    echo "               Usage: $0 view jobs_new_2026-03-08_15-47.csv"
    echo "               Or:    $0 view (uses latest in data/output/)"
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
        ;;
    7d)
        echo "========================================================"
        echo "  Job Hunt Util - Last 7 Days"
        echo "========================================================"
        run_script "scripts/build_seen.py"
        run_script "scripts/scraper.py" --hours 168
        run_script "scripts/filter_unseen.py"
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
