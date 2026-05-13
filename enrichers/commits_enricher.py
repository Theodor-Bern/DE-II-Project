#!/usr/bin/env python3
"""
Commits enricher: subscribes to `repos.raw`, queries the GitHub Core API
to count total commits per repo, and publishes the enriched record to
the `commit-topic`.

Uses the "Link header trick": calling GET /commits?per_page=1 and reading
the last-page number from the Link header gives the total commit count
in a single API call, regardless of how many commits the repo has.
"""
import os
import re
import json
import time
import requests
import pulsar

# ── Configuration ────────────────────────────────────────────────────────────
PULSAR_URL    = os.environ["PULSAR_URL"]
GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
INPUT_TOPIC   = os.environ.get("INPUT_TOPIC",  "repos.raw")
OUTPUT_TOPIC  = os.environ.get("OUTPUT_TOPIC", "commit-topic")
SUBSCRIPTION  = os.environ.get("SUBSCRIPTION", "commits-enricher-sub")
LOG_EVERY     = int(os.environ.get("LOG_EVERY", "50"))

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Regex to pull the last-page number out of the Link header
LAST_PAGE_RE = re.compile(r'<[^>]*[?&]page=(\d+)[^>]*>;\s*rel="last"')


def respect_rate_limit(resp):
    """If Core API rate limit is nearly exhausted, sleep until reset."""
    remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
    reset_ts  = int(resp.headers.get("X-RateLimit-Reset", time.time()))
    if remaining <= 5:
        wait = max(0, reset_ts - int(time.time())) + 2
        print(f"  [rate-limit] {remaining} calls left, sleeping {wait}s", flush=True)
        time.sleep(wait)


def count_commits(owner_login, repo_name):
    """
    Return total number of commits in the repo, or None if it can't be determined.

    Strategy: GET /commits?per_page=1, then read 'rel=last' from Link header.
    - If Link has rel=last → that page number is the total commit count.
    - If no Link header → either 0 or 1 commit, distinguish by response body.
    - 409 means empty repository → 0 commits.
    - 404 means repo no longer accessible → None (skip).
    """
    url = f"https://api.github.com/repos/{owner_login}/{repo_name}/commits"
    resp = requests.get(url, headers=HEADERS, params={"per_page": 1}, timeout=30)

    if resp.status_code == 409:
        return 0  # empty repo
    if resp.status_code == 404:
        return None  # gone
    if resp.status_code == 403:
        respect_rate_limit(resp)
        return None  # skip this one, next call will retry rate limit check

    resp.raise_for_status()
    respect_rate_limit(resp)

    link = resp.headers.get("Link", "")
    match = LAST_PAGE_RE.search(link)
    if match:
        return int(match.group(1))

    # No 'last' link → either 0 or 1 commits
    items = resp.json()
    return len(items) if isinstance(items, list) else 0


def main():
    print(f"Connecting to Pulsar at {PULSAR_URL}", flush=True)
    client = pulsar.Client(PULSAR_URL)
    consumer = client.subscribe(
        INPUT_TOPIC,
        subscription_name=SUBSCRIPTION,
        consumer_type=pulsar.ConsumerType.Shared,
        initial_position=pulsar.InitialPosition.Earliest,
    )
    producer = client.create_producer(OUTPUT_TOPIC)
    print(f"Subscribed to '{INPUT_TOPIC}' → producing to '{OUTPUT_TOPIC}'", flush=True)

    processed = 0
    skipped = 0
    try:
        while True:
            msg = consumer.receive()
            try:
                repo = json.loads(msg.data().decode("utf-8"))
                owner = repo.get("owner_login")
                name = repo.get("full_name", "").split("/")[-1]

                if not owner or not name:
                    consumer.acknowledge(msg)
                    skipped += 1
                    continue

                commits = count_commits(owner, name)
                if commits is None:
                    consumer.acknowledge(msg)
                    skipped += 1
                    continue

                enriched = {
                    "repo_id":      repo.get("id"),
                    "full_name":    repo.get("full_name"),
                    "language":     repo.get("language"),
                    "commit_count": commits,
                }
                producer.send(
                    json.dumps(enriched).encode("utf-8"),
                    properties={"repo_id": str(repo.get("id"))},
                )
                consumer.acknowledge(msg)
                processed += 1

                if (processed + skipped) % LOG_EVERY == 0:
                    print(f"  processed={processed}  skipped={skipped}  "
                          f"latest={repo.get('full_name')} ({commits} commits)", flush=True)

            except requests.exceptions.RequestException as e:
                # Transient network error → nack so message is redelivered
                print(f"  network error: {e}", flush=True)
                consumer.negative_acknowledge(msg)
            except Exception as e:
                print(f"  unexpected error: {e}", flush=True)
                consumer.negative_acknowledge(msg)

    except KeyboardInterrupt:
        print(f"\nFinal: processed={processed}, skipped={skipped}", flush=True)
    finally:
        producer.close()
        consumer.close()
        client.close()


if __name__ == "__main__":
    main()
