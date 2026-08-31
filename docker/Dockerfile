# Containerized sim environment — the Linux half of this repo's setup
# (what scripts/setup_wsl.sh builds inside WSL), minus WSL.
#
# x86_64 only: Elodin ships no aarch64-linux CLI, so Apple Silicon runs
# this image under Rosetta (compose pins `platform: linux/amd64`).
#
# The repos are bind-mounted at runtime (see docker-compose.yml); this
# image holds only the toolchain, the Elodin CLI, and a pre-warmed
# Python env. The entrypoint finishes anything machine-specific
# (uv sync against the mounted repo, Betaflight SITL build).

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# - build-essential/git/curl/libasound2t64: the setup_wsl.sh apt line
# - procps: sim/main.py uses pkill to reap stale SITL processes
# - gcc-arm-none-eabi: satisfies Betaflight's SDK check so the build
#   skips the ~500MB `make arm_sdk_install` download (SITL compiles
#   with the host gcc regardless)
# - mesa-vulkan-drivers/libvulkan1/vulkan-tools: lavapipe software
#   Vulkan so the headless FPV camera render works without a GPU
# - libgl1/libglib2.0-0: opencv-python runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git curl ca-certificates xz-utils \
        procps libasound2t64 \
        gcc-arm-none-eabi \
        mesa-vulkan-drivers libvulkan1 vulkan-tools \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:/root/.cargo/bin:${PATH}"

# uv (installs to /root/.local/bin)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Elodin CLI + elodin-db (installs to /root/.cargo/bin)
COPY scripts/install_elodin.sh /tmp/install_elodin.sh
RUN bash /tmp/install_elodin.sh && rm /tmp/install_elodin.sh

# The CLI swallows its FIRST real invocation to print a welcome banner and
# exits without running the script (scripts/setup_wsl.sh works around the
# same quirk). Unprimed, that sacrificial run is the container's first
# race: it exits 0 having done nothing. The banner short-circuits before
# the script is read, so any argument primes it. It marks itself done by
# creating ~/.local/share/cli; mkdir is the belt-and-braces fallback in
# case a future release changes the trigger.
RUN touch /tmp/prime.py \
    && (timeout 60 elodin run /tmp/prime.py >/dev/null 2>&1 || true) \
    && rm -f /tmp/prime.py \
    && mkdir -p /root/.local/share/cli

# Pre-warm the Python env into /opt/venv so the first `docker compose up`
# doesn't start with a full dependency download. At runtime the same path
# is a named volume (seeded from this layer) and the entrypoint re-syncs
# against the mounted repo, which is a no-op unless pyproject changed.
WORKDIR /work/elodin-sim-aigp
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen

# Where the sim looks for the companion repo (compose mounts it here)
ENV AIGP_REPO=/work/AI-GrandPrix

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Elodin render server (native editor connects here)
EXPOSE 2240

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uv", "run", "--", "elodin", "run", "sim/main.py"]
