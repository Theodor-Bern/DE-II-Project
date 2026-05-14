# syntax=docker/dockerfile:1.6
#
# de2-controller — the bootstrap image. Run this on a manually-created
# Ubuntu VM to provision and deploy the entire 4-VM analytics cluster.
#
# Build (from repo root):
#   docker build -f controller/Dockerfile -t theodorafc02/de2-controller:latest .
#
# Push:
#   docker push theodorafc02/de2-controller:latest
#
# Run (on the client VM):
#   docker run --rm -it \
#     -v ~/.ssh:/root/.ssh:ro \
#     -v ~/openrc.sh:/openrc.sh:ro \
#     -v ~/.github_tokens:/tokens/.github_tokens:ro \
#     -v $(pwd)/results:/results \
#     theodorafc02/de2-controller:latest

FROM python:3.11-slim

# OpenStack SDK + SSH client + utilities used by deploy.sh / collect.sh
RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-client \
        netcat-openbsd \
        curl \
        ca-certificates \
        gawk \
    && rm -rf /var/lib/apt/lists/*

# python-novaclient pulls in keystoneauth1 and the rest of the OpenStack stack
RUN pip install --no-cache-dir \
        python-novaclient==18.6.0 \
        python-keystoneclient==5.4.0 \
        keystoneauth1==5.5.0

WORKDIR /controller

# ── Orchestration material from controller/ ──────────────────────────────────
COPY controller/start_instances.py  ./start_instances.py
COPY controller/deploy.sh           ./deploy.sh
COPY controller/collect.sh          ./collect.sh
COPY controller/cloud-init/         ./cloud-init/

# ── Compose files from services/ — one per VM role ───────────────────────────
COPY services/broker/docker-compose.yml      ./compose-files/broker/docker-compose.yml
COPY services/producer/docker-compose.yml    ./compose-files/producer/docker-compose.yml
COPY services/enrichers/docker-compose.yml   ./compose-files/enrichers/docker-compose.yml
COPY services/aggregators/docker-compose.yml ./compose-files/aggregators/docker-compose.yml

RUN chmod +x deploy.sh collect.sh

# Default to running deploy.sh. User can override with `... collect.sh` or
# `... bash` for interactive debugging.
ENTRYPOINT []
CMD ["./deploy.sh"]
