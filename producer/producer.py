#!/usr/bin/env python3
"""
Producer: fetches repositories from the GitHub Search API and publishes them
to the Pulsar topic `repos.raw`.

Strategy:
  - Iterate over dates in a configurable window (default: 7 days back from today)
  - For each date, search repos created on that date (paginated, 100 per page, up to 10 pages)
  - Respect Search API rate limits (30 req/min authenticated → sleep when low)
  - Publish each repo as JSON to Pulsar
"""
import os
import sys
import json
import time
import datetime as dt
import requests
import pulsar

# ── Configuration via env ────────────────────────────────────────────────────
PULSAR_URL    = os.environ["PULSAR_URL"]
GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
DAYS_BACK     = int(os.environ.get("DAYS_BACK", "7"))
TOPIC         = os.environ.get("TOPIC", "repos.raw")
PER_PAGE      = 100   # GitHub max
MAX_PAGES     = 10    # GitHub returns max 1000 results = 10 pages of 100

GITHUB_API    = "https://api.github.com/search/repositories"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Fields we keep — strips out the bulky parts of the API response
KEEP_FIELDS = ["id", "full_name", "language", "created_at", "pushed_at",
               "default_branch", "stargazers_count", "forks_count"]


def keep(repo):
    """Trim a repo dict down to fields we care about."""
    trimmed = {k: repo.get(k) for k in KEEP_FIELDS}
    trimmed["owner_login"] = (repo.get("owner") or {}).get("login")
    return trimmed


def respect_rate_limit(resp):
    """If we're close to the Search API rate limit, sleep until reset."""
    remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
    reset_ts  = int(resp.headers.get("X-RateLimit-Reset", time.time()))
    if remaining <= 2:
        wait = max(0, reset_ts - int(time.time())) + 2
        print(f"  [rate-limit] {remaining} calls left, sleeping {wait}s until reset", flush=True)
        time.sleep(wait)


def fetch_day(date_str):
    """Yield trimmed repo dicts for all repos created on `date_str`."""
    query = f"created:{date_str}..{date_str}"
    for page in range(1, MAX_PAGES + 1):
        params = {"q": query, "per_page": PER_PAGE, "page": page, "sort": "stars", "order": "desc"}
        resp = requests.get(GITHUB_API, headers=HEADERS, params=params, timeout=30)

        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            respect_rate_limit(resp)
            resp = requests.get(GITHUB_API, headers=HEADERS, params=params, timeout=30)

        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            return  # no more results for this day
        for repo in items:
            yield keep(repo)

        # If we got fewer than per_page, there's no next page
        if len(items) < PER_PAGE:
            return

        respect_rate_limit(resp)


def date_range(days_back):
    """Yield ISO date strings from `days_back` ago up to (but not including) today, oldest first."""
    today = dt.date.today()
    for n in range(days_back, 0, -1):
        yield (today - dt.timedelta(days=n)).isoformat()


def main():
    print(f"Connecting to Pulsar at {PULSAR_URL}", flush=True)
    client   = pulsar.Client(PULSAR_URL)
    producer = client.create_producer(TOPIC)
    print(f"Producing to topic '{TOPIC}', scanning {DAYS_BACK} days of history", flush=True)

    total = 0
    try:
        for date_str in date_range(DAYS_BACK):
            print(f"\n── {date_str} ─────────────────", flush=True)
            day_count = 0
            for repo in fetch_day(date_str):
                payload = json.dumps(repo).encode("utf-8")
                producer.send(
                    payload,
                    properties={"repo_id": str(repo["id"]), "fetched_on": date_str},
                )
                day_count += 1
                total += 1
            print(f"  → published {day_count} repos for {date_str}  (total: {total})", flush=True)
        print(f"\nDone. Total repos published: {total}", flush=True)
    finally:
        producer.close()
        client.close()


if __name__ == "__main__":
    main()
