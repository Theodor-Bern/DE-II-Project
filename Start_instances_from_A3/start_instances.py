import time, os, sys, random, re
from os import environ as env
from novaclient import client
from keystoneauth1 import loading, session

# ── Configuration ─────────────────────────────────────────────────────────────
KEY_NAME             = "Group18-key"
FLAVOR               = "ssc.medium"
IMAGE_NAME           = "Ubuntu 22.04 - 2024.01.15"
PRIVATE_NET          = "UPPMAX 2026/1-24 Internal IPv4 Network"
SECURITY_GROUPS      = ["default"]
# ─────────────────────────────────────────────────────────────────────────────

identifier = random.randint(1000, 9999)

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


def read_cfg(filename):
    """Read a cloud-cfg file as a string (so we can do template substitution)."""
    path = os.path.join(os.getcwd(), filename)
    if not os.path.isfile(path):
        sys.exit(f"ERROR: {filename} not found in current directory")
    with open(path) as f:
        return f.read()


def launch(name, userdata_string):
    """Launch a VM with userdata passed as a string."""
    return nova.servers.create(
        name           = f"{name}-{identifier}",
        image          = image,
        flavor         = flavor,
        key_name       = KEY_NAME,
        userdata       = userdata_string,
        nics           = nics,
        security_groups= SECURITY_GROUPS
    )


def wait_for_ip(instance):
    """Block until the instance has been assigned a private IPv4 address."""
    while True:
        updated = nova.servers.get(instance.id)
        if updated.networks.get(PRIVATE_NET):
            for network in updated.networks[PRIVATE_NET]:
                if re.match(r'\d+\.\d+\.\d+\.\d+', network):
                    return network, updated
        time.sleep(5)


def wait_for_active(instance, name):
    """Block until the instance is ACTIVE."""
    while True:
        updated = nova.servers.get(instance.id)
        if updated.status == 'ACTIVE':
            return updated
        print(f"  {name} is in {updated.status} state...")
        time.sleep(5)


# ── Phase 1: Launch broker, wait for IP ───────────────────────────────────────
print("\n[Phase 1] Launching broker VM...")
cfg_broker = read_cfg('broker-cloud-cfg.txt')
broker = launch("broker-vm", cfg_broker)

print("Waiting for broker IP assignment...")
broker_ip, broker = wait_for_ip(broker)
print(f"Broker IP: {broker_ip}")

# ── Phase 2: Inject broker IP into the other cloud-cfg files, then launch ─────
print("\n[Phase 2] Launching producer, consumer, aggregator with BROKER_IP injected...")

cfg_producer   = read_cfg('producer-cloud-cfg.txt').replace('{{BROKER_IP}}', broker_ip)
cfg_consumer   = read_cfg('consumer-cloud-cfg.txt').replace('{{BROKER_IP}}', broker_ip)
cfg_aggregator = read_cfg('aggregator-cloud-cfg.txt').replace('{{BROKER_IP}}', broker_ip)

producer   = launch("producer-vm",   cfg_producer)
consumer   = launch("consumer-vm",   cfg_consumer)
aggregator = launch("aggregator-vm", cfg_aggregator)

instances = {
    "broker-vm":     broker,
    "producer-vm":   producer,
    "consumer-vm":   consumer,
    "aggregator-vm": aggregator,
}

# ── Wait for all to be ACTIVE ────────────────────────────────────────────────
print("\nWaiting for all instances to become ACTIVE...")
time.sleep(10)
for name, inst in instances.items():
    instances[name] = wait_for_active(inst, name)

# ── Summary ──────────────────────────────────────────────────────────────────
print("\n── Instance Summary ──────────────────────────────")
for name, inst in instances.items():
    for network in inst.networks[PRIVATE_NET]:
        if re.match(r'\d+\.\d+\.\d+\.\d+', network):
            print(f"  {inst.name}  →  {network}")
            break

print(f"\nBroker reachable at: pulsar://{broker_ip}:6650")
print("All VMs ACTIVE.")
