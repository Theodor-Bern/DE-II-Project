# start_instances.py — Project 2: GitHub Analytics
# ===================================================
# Launches 4 VMs via OpenStack API:
#   - producer-vm      (fetches GitHub data, publishes to Pulsar)
#   - consumer-vm1     (Q1 + Q2 analytics)
#   - consumer-vm2     (Q3 + Q4 analytics)
#   - aggregator-vm    (compiles results, generates graphs)
#
# The Broker VM (Pulsar) is assumed to already be running.
#
# Before running:
#   1. source your RC file:  source UPPMAX_2026_1-24-openrc.sh
#   2. Replace <KEY-NAME> below with your SSH key name from SSC dashboard
#   3. Replace the SSH public key in each cloud-cfg file with your own
#   4. Run: python3 start_instances.py

import time, os, sys, random, re
from os import environ as env
from novaclient import client
import keystoneclient.v3.client as ksclient
from keystoneauth1 import loading
from keystoneauth1 import session

# ── Configuration — edit these ────────────────────────────────────────────────
KEY_NAME             = "Group18-key"                          # Your SSH key name on SSC
FLAVOR               = "ssc.medium"
IMAGE_NAME           = "Ubuntu 22.04 - 2024.01.15"
PRIVATE_NET          = "UPPMAX 2026/1-24 Internal IPv4 Network"
SECURITY_GROUPS      = ["default"]
# ─────────────────────────────────────────────────────────────────────────────

identifier = random.randint(1000, 9999)

# Auth
loader = loading.get_plugin_loader('password')
auth = loader.load_from_options(
    auth_url         = env['OS_AUTH_URL'],
    username         = env['OS_USERNAME'],
    password         = env['OS_PASSWORD'],
    project_name     = env['OS_PROJECT_NAME'],
    project_domain_id= env['OS_PROJECT_DOMAIN_ID'],
    user_domain_name = env['OS_USER_DOMAIN_NAME']
)
sess = session.Session(auth=auth)
nova = client.Client('2.1', session=sess)
print("User authorization completed.")

image  = nova.glance.find_image(IMAGE_NAME)
flavor = nova.flavors.find(name=FLAVOR)
net    = nova.neutron.find_network(PRIVATE_NET)
nics   = [{'net-id': net.id}]

# Load cloud-cfg files
def load_cfg(filename):
    path = os.getcwd() + '/' + filename
    if os.path.isfile(path):
        return open(path)
    sys.exit(f"ERROR: {filename} not found in current directory")

cfg_producer   = load_cfg('producer-cloud-cfg.txt')
cfg_consumer1  = load_cfg('consumer1-cloud-cfg.txt')
cfg_consumer2  = load_cfg('consumer2-cloud-cfg.txt')
cfg_aggregator = load_cfg('aggregator-cloud-cfg.txt')

# Launch all 4 VMs
print("\nCreating instances...")

instance_producer = nova.servers.create(
    name           = f"producer-vm-{identifier}",
    image          = image,
    flavor         = flavor,
    key_name       = KEY_NAME,
    userdata       = cfg_producer,
    nics           = nics,
    security_groups= SECURITY_GROUPS
)

instance_consumer1 = nova.servers.create(
    name           = f"consumer-vm1-{identifier}",
    image          = image,
    flavor         = flavor,
    key_name       = KEY_NAME,
    userdata       = cfg_consumer1,
    nics           = nics,
    security_groups= SECURITY_GROUPS
)

instance_consumer2 = nova.servers.create(
    name           = f"consumer-vm2-{identifier}",
    image          = image,
    flavor         = flavor,
    key_name       = KEY_NAME,
    userdata       = cfg_consumer2,
    nics           = nics,
    security_groups= SECURITY_GROUPS
)

instance_aggregator = nova.servers.create(
    name           = f"aggregator-vm-{identifier}",
    image          = image,
    flavor         = flavor,
    key_name       = KEY_NAME,
    userdata       = cfg_aggregator,
    nics           = nics,
    security_groups= SECURITY_GROUPS
)

instances = {
    "producer-vm":   instance_producer,
    "consumer-vm1":  instance_consumer1,
    "consumer-vm2":  instance_consumer2,
    "aggregator-vm": instance_aggregator,
}

# Wait for all to leave BUILD state
print("\nWaiting for instances to become ACTIVE...")
time.sleep(10)

active = {name: False for name in instances}

while not all(active.values()):
    for name, inst in instances.items():
        updated = nova.servers.get(inst.id)
        instances[name] = updated
        status = updated.status
        if status == 'ACTIVE':
            active[name] = True
        else:
            print(f"  {name} is in {status} state...")
    if not all(active.values()):
        time.sleep(5)

# Print IP addresses
print("\n── Instance Summary ──────────────────────────────")
for name, inst in instances.items():
    for network in inst.networks[PRIVATE_NET]:
        if re.match(r'\d+\.\d+\.\d+\.\d+', network):
            print(f"  {inst.name}  →  {network}")
            break

print("\nAll VMs are ACTIVE.")
print("Next steps:")
print("  1. Attach floating IPs if needed (SSC dashboard)")
print("  2. SCP your scripts to each VM")
print("  3. Set BROKER_IP in each script to your broker VM's private IP")
print("  4. Start Pulsar on broker, then consumers, then aggregator, then producer")
