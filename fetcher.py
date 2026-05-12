import requests
import json
import time
import os

TOKEN = os.getenv("GITHUB_TOKEN")

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
}

MIN_STARS = 2
MIN_FORKS = 1

def passes_filter(repo):
    if repo.get("language") is None:
        return False
    if repo.get("stargazers_count", 0) < MIN_STARS:
        return False
    if repo.get("forks_count", 0) < MIN_FORKS:
        return False
    return True

def extract_fields(repo):
    return {
        "name":      repo["full_name"],
        "language":  repo["language"],
        "stars":     repo["stargazers_count"],
        "forks":     repo["forks_count"],
        "pushed_at": repo["pushed_at"],
    }

def fetch_day_all_pages(date_str):
    url    = "https://api.github.com/search/repositories"
    passed = []

    for page in range(1, 11):
        params = {
            "q":        f"created:{date_str}",
            "sort":     "stars",
            "order":    "desc",
            "per_page": 100,
            "page":     page,
        }

        r = requests.get(url, params=params, headers=headers)
        remaining = r.headers.get("X-RateLimit-Remaining")
        print(f"  Sida {page}: status {r.status_code}, search kvar: {remaining}")

        if r.status_code != 200:
            print("  Fel:", r.json().get("message"))
            break

        items = r.json().get("items", [])
        if not items:
            print("  Inga fler resultat")
            break

        for repo in items:
            if passes_filter(repo):
                passed.append(extract_fields(repo))

        time.sleep(2)  # var snäll mot API:et

    return passed

# ── Kör ───────────────────────────────────────────────────
date = "2024-06-01"
print(f"=== Hämtar alla sidor för {date} ===\n")
repos = fetch_day_all_pages(date)

print(f"\nTotalt klarade filtret: {len(repos)} repos")

# Språkfördelning
from collections import Counter
langs = Counter(r["language"] for r in repos)
print("\nTopp 10 språk den dagen:")
for lang, count in langs.most_common(10):
    print(f"  {lang:<20} {count}")