# ─── User Configuration ─────────────────────────────────────
# Edit this file to customize your job search
# All other scripts read from this config

# Job titles to search for
TITLES = [
    "Software Engineer",
    "Backend Engineer",
    "Java Developer",
    "Python Developer",
    "Full Stack Engineer",
    "Senior Software Engineer",
    "Software Developer",
]

# Locations to search in
LOCATIONS = [
    "Pune, India",
    "Mumbai, India",
    "Hyderabad, India",
]

# Sites to scrape (linkedin, indeed, zip_recruiter, google)
# Note: Glassdoor is automatically removed (no India support)
SITES = ["linkedin", "indeed", "zip_recruiter", "google"]

# Number of results to fetch per title/location combination
RESULTS_PER_SEARCH = 20

# ──────────────────────────────────────────────────────────
