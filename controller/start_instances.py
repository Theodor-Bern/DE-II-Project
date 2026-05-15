#!/usr/bin/env python3
"""
Provisions the 4-VM cluster on UPPMAX OpenStack:

  Phase 1: Launch broker VM. Wait for IP.
  Phase 2: Inject BROKER_IP into the other cloud-init files. Launch the rest.
  Phase 3: Wait until all 4 are ACTIVE *and* have a private IP, print summary.

Writes a shell-sourceable inventory file (default: /controller/inventory.env)
that deploy.sh consumes:

  BROKER_IP=10.x.y.z
  PRODUCER_IP=10.x.y.z
  CONSUMER_IP=10.x.y.z
  AGGREGATOR_IP=10.x.y.z
"""
import os
import re
import sys
import time
import random
from os import environ as env

from novaclient import client
from keystoneauth1 import loading, session

# ── Configuration ─────────────────────────────────────────────────────────────
KEY_NAME        = env.get("KEY_NAME",       "Group18-key")
FLAVOR          = env.get("FLAVOR",         "ssc.medium")
IMAGE_NAME      = env.get("IMAGE_NAME",     "Ubuntu 22.04 - 2024.01.15")
PRIVATE_NET     = env.get("PRIVATE_NET",    "UPPMAX 2026/1-24 Internal IPv4 Network")
SECURITY_GROUPS = ["default"]

# Where to look for cloud-init files (overridable for local testing)
CLOUD_INIT_DIR  = env.get("CLOUD_INIT_DIR", "/controller/cloud-init")
INVENTORY_PATH  = env.get("INVENTORY_PATH", "/controller/state/inventory.env")
# ─────────────────────────────────────────────────────────────────────────────

identifier = random.randint(1000, 9999)

# ── Auth ─────────────────────────────────────────────────────────────────────
loader = loading.get_plugin_loader('password')
auth = loader.load_from_options(
    auth_url         = env['OS_AUTH_URL'],
    username         = env['OS_USERNAME'],
    password         = env['OS_PASSWORD'],
    project_name     = env['OS_PROJECT_NAME'],
    project_domain_id= env['OS_PROJECT_DOMAIN_ID'],
    user_domain_name = env['OS_USER_DOMAIN_NAME'],
)
sess = session.Session(auth=auth)
nova = client.Client('2.1', session=sess)
print("User authorization completed.", flush=True)

image  = nova.glance.find_image(IMAGE_NAME)
flavor = nova.flavors.find(name=FLAVOR)
net    = nova.neutron.find_network(PRIVATE_NET)
nics   = [{'net-id': net.id}]


def read_cfg(filename):
    """Read a cloud-init file from CLOUD_INIT_DIR as a string."""
    path = os.path.join(CLOUD_INIT_DIR, filename)
    if not os.path.isfile(path):
        sys.exit(f"ERROR: {path} not found")
    with open(path) as f:
        return f.read()


def launch(name, userdata_string):
    return nova.servers.create(
        name           = f"{name}-{identifier}",
        image          = image,
        flavor         = flavor,
        key_name       = KEY_NAME,
        userdata       = userdata_string,
        nics           = nics,
        security_groups= SECURITY_GROUPS,
    )


def first_ipv4(instance):
    """Return the first IPv4 on PRIVATE_NET, or None if not bound yet."""
    nets = instance.networks or {}
    addrs = nets.get(PRIVATE_NET, [])
    for n in addrs:
        if re.match(r'\d+\.\d+\.\d+\.\d+', n):
            return n
    return None


def wait_for_ip(instance):
    """Poll until the instance has a private IPv4 address. Returns (ip, instance)."""
    while True:
        updated = nova.servers.get(instance.id)
        ip = first_ipv4(updated)
        if ip:
            return ip, updated
        time.sleep(5)


def wait_for_active(instance, name):
    """Poll until status == ACTIVE. Returns updated instance."""
    while True:
        updated = nova.servers.get(instance.id)
        if updated.status == 'ACTIVE':
            return updated
        if updated.status == 'ERROR':
            sys.exit(f"ERROR: {name} entered ERROR state")
        print(f"  {name} is in {updated.status} state...", flush=True)
        time.sleep(5)


# ── Phase 1: broker ───────────────────────────────────────────────────────────
print("\n[Phase 1] Launching broker VM...", flush=True)
broker = launch("broker-vm", read_cfg("broker.yaml"))

print("Waiting for broker IP...", flush=True)
broker_ip, broker = wait_for_ip(broker)
print(f"Broker IP: {broker_ip}", flush=True)

# ── Phase 2: producer, consumer, aggregator (with BROKER_IP injected) ─────────
print("\n[Phase 2] Launching producer, consumer, aggregator...", flush=True)

cfg_producer   = read_cfg("producer.yaml").replace("{{BROKER_IP}}", broker_ip)
cfg_consumer   = read_cfg("consumer.yaml").replace("{{BROKER_IP}}", broker_ip)
cfg_aggregator = read_cfg("aggregator.yaml").replace("{{BROKER_IP}}", broker_ip)

producer   = launch("producer-vm",   cfg_producer)
consumer   = launch("consumer-vm",   cfg_consumer)
aggregator = launch("aggregator-vm", cfg_aggregator)

instances = {
    "broker":     broker,
    "producer":   producer,
    "consumer":   consumer,
    "aggregator": aggregator,
}

# ── Phase 3: wait for ACTIVE *and* network binding ───────────────────────────
print("\nWaiting for all instances to become ACTIVE and get a private IP...", flush=True)
time.sleep(10)
for role, inst in instances.items():
    inst = wait_for_active(inst, role)
    # ACTIVE != network bound — poll until Neutron has attached the port
    _, inst = wait_for_ip(inst)
    instances[role] = inst

# ── Summary + inventory ──────────────────────────────────────────────────────
print("\n── Instance Summary ──────────────────────────────", flush=True)
ips = {}
for role, inst in instances.items():
    ip = first_ipv4(inst)
    ips[role] = ip
    print(f"  {inst.name:<30s} ({role})  →  {ip}", flush=True)

# Write inventory file that deploy.sh sources
os.makedirs(os.path.dirname(INVENTORY_PATH), exist_ok=True)
with open(INVENTORY_PATH, "w") as f:
    f.write(f"BROKER_IP={ips['broker']}\n")
    f.write(f"PRODUCER_IP={ips['producer']}\n")
    f.write(f"CONSUMER_IP={ips['consumer']}\n")
    f.write(f"AGGREGATOR_IP={ips['aggregator']}\n")

print(f"\nInventory written to {INVENTORY_PATH}", flush=True)
print(f"Broker reachable at: pulsar://{ips['broker']}:6650", flush=True)
print("All VMs ACTIVE.", flush=True)
