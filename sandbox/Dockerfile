# syntax=docker/dockerfile:1.7
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HOSTNAME=sandbox

# Keep apt's package cache in a BuildKit cache mount instead of inside
# each layer — reruns reuse downloaded debs.
RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' \
        > /etc/apt/apt.conf.d/keep-cache

# Layer 1: base packages, fonts, locales, default-Ubuntu Python.
# No third-party PPAs — Ubuntu 22.04 ships Python 3.10 natively, so we
# drop ppa:deadsnakes. Avoiding launchpad PPAs also makes the build work
# on networks where ppa.launchpadcontent.net is firewalled.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        sudo bc curl wget gnupg ca-certificates git \
        software-properties-common \
        xvfb x11vnc xterm socat supervisor websockify \
        python3 python3-venv python3-dev python3-pip \
        fonts-noto-cjk fonts-noto-color-emoji \
        language-pack-zh-hans locales && \
    locale-gen zh_CN.UTF-8 && \
    git config --system user.email "agent@helix.local" && \
    git config --system user.name "Helix Agent"

# ubuntu user with passwordless sudo
RUN useradd -m -d /home/ubuntu -s /bin/bash ubuntu && \
    echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu

# Node 20 from nodesource (deb.nodesource.com — public CDN, reachable)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs

# npm registry pointing at npmmirror — reliable from inside Docker build
# network. (npmjs.org direct is blocked on some restrictive networks.)
RUN npm config set registry https://registry.npmmirror.com -g

# uv (cached pip)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install uv

# pnpm — used by helix-dev-runner.sh to bring up Vite dev servers
RUN npm install -g pnpm@9 && \
    pnpm config set registry https://registry.npmmirror.com

# Playwright Chromium — replaces the upstream chromium PPA
# (ppa:xtradeb/apps), which is unreachable on networks that firewall
# launchpad. Playwright bundles its own multi-arch (amd64 + arm64)
# Chromium build, fetched from a public CDN. `--with-deps` apt-installs
# all system libs the binary needs (libnss3, libatk*, libdrm, etc.).
# Symlink /usr/bin/chromium so supervisord's `command=chromium` works
# without any conf changes.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/root/.npm \
    npx -y playwright@1.49.1 install --with-deps chromium && \
    chrome_bin=$(ls -d /opt/playwright/chromium-*/chrome-linux/chrome | head -n1) && \
    ln -sf "$chrome_bin" /usr/bin/chromium && \
    chmod -R a+rX /opt/playwright

WORKDIR /app

# Sandbox python deps (cached uv downloads)
COPY sandbox/pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# helixcli — installed BEFORE sandbox source COPY so source edits don't
# bust the (more expensive) helixcli venv layer.
COPY helixcli /tmp/helixcli
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --python python3 /opt/helixcli-venv && \
    uv pip install --python /opt/helixcli-venv/bin/python /tmp/helixcli && \
    ln -sf /opt/helixcli-venv/bin/helixcli /usr/local/bin/helixcli && \
    chmod -R a+rX /opt/helixcli-venv && \
    rm -rf /tmp/helixcli

# Sandbox source + service config
COPY sandbox/ ./
COPY sandbox/supervisord.conf /etc/supervisor/conf.d/app.conf
COPY sandbox/helix-dev-runner.sh /usr/local/bin/helix-dev-runner.sh
RUN chmod +x /usr/local/bin/helix-dev-runner.sh && \
    chown -R ubuntu:ubuntu /app

EXPOSE 8080 9222 5900 5901

ENV UVI_ARGS=""
ENV CHROME_ARGS=""

CMD ["supervisord", "-n", "-c", "/app/supervisord.conf"]
