#!/usr/bin/env python3
"""
Language aggregator: subscribes to `repos.raw`, counts repos per language,
and periodically logs the top-N languages.

Answers project question Q1: most common programming languages.

Configurable via env:
  TOP_N         — how many languages to show (default 10)
  REPORT_EVERY  — emit top-N after this many new messages (default 100)
"""
import os
import json
import collections
import pulsar

PULSAR_URL    = os.environ["PULSAR_URL"]
TOPIC         = os.environ.get("TOPIC", "repos.raw")
SUBSCRIPTION  = os.environ.get("SUBSCRIPTION", "language-aggregator-sub")
TOP_N         = int(os.environ.get("TOP_N", "10"))
REPORT_EVERY  = int(os.environ.get("REPORT_EVERY", "100"))


def render_top(counter, n):
    """Return a formatted top-N table as a string."""
    total = sum(counter.values())
    lines = [f"── Top {n} languages (out of {total} repos) ──"]
    for i, (lang, count) in enumerate(counter.most_common(n), 1):
        pct = 100 * count / total if total else 0
        label = lang if lang else "(none)"
        lines.append(f"  {i:2d}. {label:<20s}  {count:>6d}  ({pct:.1f}%)")
    return "\n".join(lines)


def main():
    print(f"Connecting to Pulsar at {PULSAR_URL}", flush=True)
    client = pulsar.Client(PULSAR_URL)
    consumer = client.subscribe(
        TOPIC,
        subscription_name=SUBSCRIPTION,
        consumer_type=pulsar.ConsumerType.Shared,
        initial_position=pulsar.InitialPosition.Earliest,
    )
    print(f"Subscribed to '{TOPIC}' as '{SUBSCRIPTION}'", flush=True)
    print(f"Reporting top {TOP_N} every {REPORT_EVERY} messages", flush=True)

    counter = collections.Counter()
    seen = 0

    try:
        while True:
            msg = consumer.receive()
            try:
                repo = json.loads(msg.data().decode("utf-8"))
                counter[repo.get("language")] += 1
                consumer.acknowledge(msg)
                seen += 1
                if seen % REPORT_EVERY == 0:
                    print("\n" + render_top(counter, TOP_N), flush=True)
            except Exception as e:
                print(f"  error: {e}", flush=True)
                consumer.negative_acknowledge(msg)
    except KeyboardInterrupt:
        print("\n── Final ──", flush=True)
        print(render_top(counter, TOP_N), flush=True)
    finally:
        consumer.close()
        client.close()


if __name__ == "__main__":
    main()
