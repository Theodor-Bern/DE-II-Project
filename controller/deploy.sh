#!/usr/bin/env bash
# deploy.sh — entrypoint for the de2-controller image.
#
# Runs inside the controller container. Expects mounted:
#   /openrc.sh                       — OpenStack RC (sourced for OS_* vars)
#   /root/.ssh/<KEY>.pem             — private SSH key for the VMs
#   /tokens/.github_tokens           — GITHUB_TOKEN=ghp_...
#
# Phases:
#   1) source openrc, run start_instances.py → inventory.env
#   2) wait for cloud-init on all 4 VMs
#   3) SCP compose-files + tokens to each VM
#   4) docker compose up in order: broker → aggregator → consumer → producer
#   5) print summary, exit

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
SSH_KEY="${SSH_KEY:-/root/.ssh/Group18-key.pem}"
SSH_USER="${SSH_USER:-ubuntu}"
SSH_OPTS=(-i "$SSH_KEY"
          -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR)

OPENRC="${OPENRC:-/openrc.sh}"
SECRETS_FILE="${SECRETS_FILE:-/secrets/.openstack-env}"
TOKENS_FILE="${TOKENS_FILE:-/tokens/.github_tokens}"
INVENTORY="${INVENTORY:-/controller/state/inventory.env}"

COMPOSE_DIR="/controller/compose-files"
CLOUD_INIT_WAIT_SECS="${CLOUD_INIT_WAIT_SECS:-600}"   # 10 min cap
BROKER_WAIT_SECS="${BROKER_WAIT_SECS:-180}"           # 3 min cap

log()  { echo -e "\033[1;34m[deploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[deploy]\033[0m $*"; }
die()  { echo -e "\033[1;31m[deploy]\033[0m $*"; exit 1; }

# ── Sanity checks ────────────────────────────────────────────────────────────
[[ -f "$OPENRC" ]]      || die "OpenStack RC file not found at $OPENRC (mount it with -v)"
[[ -f "$SSH_KEY" ]]     || die "SSH key not found at $SSH_KEY (mount ~/.ssh into /root/.ssh)"
[[ -f "$TOKENS_FILE" ]] || die "GitHub tokens file not found at $TOKENS_FILE"

# Verify key permissions are tight enough that ssh won't refuse it.
# We can't chmod on read-only mounts; rely on host-side permissions.
perms=$(stat -c '%a' "$SSH_KEY" 2>/dev/null || echo "")
if [[ -n "$perms" && "$perms" != "600" && "$perms" != "400" ]]; then
    warn "SSH key $SSH_KEY has permissions $perms — ssh will likely refuse it."
    warn "Run on the host: chmod 600 ~/.ssh/<keyname>"
fi

# ── Phase 1: provision VMs ───────────────────────────────────────────────────
log "Sourcing OpenStack credentials"
source "$OPENRC"

if [[ -f "$SECRETS_FILE" ]]; then
    log "Loading secrets from $SECRETS_FILE"
    # shellcheck disable=SC1090
    set -a; source "$SECRETS_FILE"; set +a
fi

log "Running start_instances.py — this provisions broker first, then the rest"
python3 /controller/start_instances.py

[[ -f "$INVENTORY" ]] || die "Inventory not written — start_instances.py failed"

source "$INVENTORY"
log "Inventory loaded:"
log "  BROKER_IP=$BROKER_IP"
log "  PRODUCER_IP=$PRODUCER_IP"
log "  CONSUMER_IP=$CONSUMER_IP"
log "  AGGREGATOR_IP=$AGGREGATOR_IP"

# ── Phase 2: wait for cloud-init on all VMs ──────────────────────────────────
wait_for_cloud_init() {
    local ip=$1 role=$2 deadline=$(( $(date +%s) + CLOUD_INIT_WAIT_SECS ))
    log "Waiting for cloud-init on $role ($ip)..."
    while (( $(date +%s) < deadline )); do
        if ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "test -f /home/ubuntu/.cloud-init-done" 2>/dev/null; then
            log "  $role ready"
            return 0
        fi
        sleep 10
    done
    die "$role ($ip) did not finish cloud-init within ${CLOUD_INIT_WAIT_SECS}s"
}

wait_for_cloud_init "$BROKER_IP"     "broker"
wait_for_cloud_init "$AGGREGATOR_IP" "aggregator"
wait_for_cloud_init "$CONSUMER_IP"   "consumer"
wait_for_cloud_init "$PRODUCER_IP"   "producer"

# ── Phase 3: distribute compose files + tokens ──────────────────────────────
distribute() {
    local ip=$1 role=$2 compose_subdir=$3 needs_tokens=$4
    log "Distributing files to $role ($ip)"

    ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "mkdir -p /home/ubuntu/$role"
    scp "${SSH_OPTS[@]}" "$COMPOSE_DIR/$compose_subdir/docker-compose.yml" \
        "$SSH_USER@$ip:/home/ubuntu/$role/docker-compose.yml"

    if [[ "$needs_tokens" == "yes" ]]; then
        scp "${SSH_OPTS[@]}" "$TOKENS_FILE" \
            "$SSH_USER@$ip:/home/ubuntu/.github_tokens"
        ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "chmod 600 /home/ubuntu/.github_tokens"
    fi
}

distribute "$BROKER_IP"     broker      broker       no
distribute "$AGGREGATOR_IP" aggregator  aggregators  no
distribute "$CONSUMER_IP"   consumer    enrichers    yes
distribute "$PRODUCER_IP"   producer    producer     yes

# ── Phase 4: start services in correct order ────────────────────────────────
start_service() {
    local ip=$1 role=$2
    log "Starting $role on $ip"
    ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" \
        "cd /home/ubuntu/$role && sudo docker compose up -d"
}

start_service "$BROKER_IP" broker

log "Waiting for Pulsar broker to accept connections..."
deadline=$(( $(date +%s) + BROKER_WAIT_SECS ))
while (( $(date +%s) < deadline )); do
    if ssh "${SSH_OPTS[@]}" "$SSH_USER@$BROKER_IP" \
         "nc -z localhost 6650" 2>/dev/null; then
        log "Pulsar is up"
        break
    fi
    sleep 5
done
ssh "${SSH_OPTS[@]}" "$SSH_USER@$BROKER_IP" "nc -z localhost 6650" 2>/dev/null \
    || die "Pulsar broker never came up on port 6650"

# Then aggregators and consumers (so they're ready when producer publishes)
start_service "$AGGREGATOR_IP" aggregator
start_service "$CONSUMER_IP"   consumer

# Give consumers a moment to subscribe before producer fires
sleep 5

# Finally producer
start_service "$PRODUCER_IP"   producer

# ── Summary ──────────────────────────────────────────────────────────────────
log "── Cluster up ────────────────────────────────────────"
log "  Broker:     ssh ubuntu@$BROKER_IP     (pulsar on :6650, admin on :8080)"
log "  Aggregator: ssh ubuntu@$AGGREGATOR_IP (4 aggregator containers)"
log "  Consumer:   ssh ubuntu@$CONSUMER_IP   (commits + test enrichers)"
log "  Producer:   ssh ubuntu@$PRODUCER_IP   (runs once, then exits)"
log ""
log "All services running in background. Use collect.sh to fetch results."
