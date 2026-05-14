#!/usr/bin/env bash
# collect.sh — fetch aggregator logs from the aggregator VM.
#
# Run this AFTER deploy.sh has set up the cluster. Can be run repeatedly —
# each invocation overwrites the previous snapshot with the latest log content.
#
# Outputs to /results/ inside the container. Mount a host directory there to
# get the files out:
#
#   docker run --rm -it \
#     -v ~/.ssh:/root/.ssh:ro \
#     -v ~/openrc.sh:/openrc.sh:ro \
#     -v $(pwd)/results:/results \
#     theodorafc02/de2-controller:latest \
#     /controller/collect.sh

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
SSH_KEY="${SSH_KEY:-/root/.ssh/Group18-key.pem}"
SSH_USER="${SSH_USER:-ubuntu}"
SSH_OPTS=(-i "$SSH_KEY"
          -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR)

INVENTORY="${INVENTORY:-/controller/state/inventory.env}"
RESULTS_DIR="${RESULTS_DIR:-/results}"

log()  { echo -e "\033[1;34m[collect]\033[0m $*"; }
die()  { echo -e "\033[1;31m[collect]\033[0m $*"; exit 1; }

# ── Sanity ───────────────────────────────────────────────────────────────────
[[ -f "$SSH_KEY" ]]   || die "SSH key not found at $SSH_KEY"
[[ -f "$INVENTORY" ]] || die "Inventory not found at $INVENTORY — has deploy.sh run?"

chmod 600 "$SSH_KEY"

# shellcheck disable=SC1090
source "$INVENTORY"
[[ -n "${AGGREGATOR_IP:-}" ]] || die "AGGREGATOR_IP missing from inventory"

mkdir -p "$RESULTS_DIR"
timestamp=$(date +"%Y%m%d-%H%M%S")
snapshot_dir="$RESULTS_DIR/snapshot-$timestamp"
mkdir -p "$snapshot_dir"

log "Snapshot directory: $snapshot_dir"

# ── Fetch logs per container ────────────────────────────────────────────────
containers=(
    language-aggregator
    commit-aggregator
    test-aggregator
    ci-aggregator
)

for c in "${containers[@]}"; do
    out="$snapshot_dir/$c.log"
    log "  fetching $c → $out"
    ssh "${SSH_OPTS[@]}" "$SSH_USER@$AGGREGATOR_IP" \
        "sudo docker logs $c 2>&1" > "$out" || {
        log "    (warning) failed to fetch $c"
    }
done

# ── Also grab the "last reported top-N" from each log for a quick summary ───
summary="$snapshot_dir/SUMMARY.txt"
{
    echo "── Snapshot $timestamp ─────────────────────────────────────────────"
    echo ""
    for c in "${containers[@]}"; do
        echo "═══════════════════════════════════════════════════════════════════"
        echo "  $c — latest top-N"
        echo "═══════════════════════════════════════════════════════════════════"
        # The aggregator scripts print "── Top N ... ──" blocks. Grab the last one.
        awk '/── Top/{block=""} {block=block $0 "\n"} END{printf "%s", block}' \
            "$snapshot_dir/$c.log" || echo "(no output)"
        echo ""
    done
} > "$summary"

log "Done. Snapshot at $snapshot_dir"
log "Quick summary: $summary"
