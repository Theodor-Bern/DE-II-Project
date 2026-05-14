#!/usr/bin/env python3
"""
Language aggregator with simple DONE-control logic.

Subscribes to `repos.raw`, counts repos per language, and sends a DONE event to
`repos.raw.control` after it has processed each repo. It then acknowledges the
original `repos.raw` message.
"""
import os
import json
import time
import collections
import pulsar

PULSAR_URL    = os.environ["PULSAR_URL"]
TOPIC         = os.environ.get("TOPIC", "repos.raw")
CONTROL_TOPIC = os.environ.get("CONTROL_TOPIC", "repos.raw.control")
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


def send_done(control_producer, repo, stage, status="ok", error=None):
    """Send application-level DONE event to the producer."""
    event = {
        "type": "DONE",
        "run_id": repo.get("run_id"),
        "job_id": repo.get("job_id"),
        "repo_id": str(repo.get("id")),
        "full_name": repo.get("full_name"),
        "stage": stage,
        "status": status,
        "error": str(error) if error else None,
        "ts": time.time(),
    }
    control_producer.send(
        json.dumps(event).encode("utf-8"),
        properties={
            "type": "DONE",
            "stage": stage,
            "status": status,
            "run_id": str(repo.get("run_id")),
            "job_id": str(repo.get("job_id")),
            "repo_id": str(repo.get("id")),
        },
    )


def main():
    print(f"Connecting to Pulsar at {PULSAR_URL}", flush=True)
    client = pulsar.Client(PULSAR_URL)

    consumer = client.subscribe(
        TOPIC,
        subscription_name=SUBSCRIPTION,
        consumer_type=pulsar.ConsumerType.Shared,
        initial_position=pulsar.InitialPosition.Earliest,
        receiver_queue_size=1,
    )

    control_producer = client.create_producer(CONTROL_TOPIC)

    print(f"Subscribed to '{TOPIC}' as '{SUBSCRIPTION}'", flush=True)
    print(f"Sending DONE events to '{CONTROL_TOPIC}'", flush=True)
    print(f"Reporting top {TOP_N} every {REPORT_EVERY} messages", flush=True)

    counter = collections.Counter()
    seen = 0

    try:
        while True:
            msg = consumer.receive()
            try:
                repo = json.loads(msg.data().decode("utf-8"))

                # Do the actual work first.
                counter[repo.get("language")] += 1

                # Then notify the producer and only after that ack repos.raw.
                send_done(control_producer, repo, stage="language", status="ok")
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
        control_producer.close()
        consumer.close()
        client.close()


if __name__ == "__main__":
    main()
