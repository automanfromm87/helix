FROM ubuntu:22.04

# Avoid interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Set hostname to sandbox
ENV HOSTNAME=sandbox

# Configure apt source to use Aliyun mirror
RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list && \
    sed -i 's|http://security.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list && \
    sed -i 's|http://ports.ubuntu.com/ubuntu-ports/|http://mirrors.aliyun.com/ubuntu-ports/|g' /etc/apt/sources.list

# Update and install basic tools
RUN apt-get update && apt-get install -y \
    sudo \
    bc \
    curl \
    wget \
    gnupg \
    software-properties-common \
    xvfb \
    x11vnc \
    xterm \
    socat \
    supervisor \
    websockify \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create user ubuntu and grant sudo privileges
RUN useradd -m -d /home/ubuntu -s /bin/bash ubuntu && \
    echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu

# Install Python 3.10.12
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.10 python3.10-venv python3.10-dev python3-pip && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip3 install uv

# Configure uv to use Aliyun mirror
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# Install Node.js 20.18.0
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Configure npm to use Aliyun mirror
RUN npm config set registry https://registry.npmmirror.com

# Install pnpm (faster + content-addressable global store, used by the
# helix-dev-runner to bring up Vite dev servers automatically).
RUN npm install -g pnpm@9 && pnpm config set registry https://registry.npmmirror.com

# Install Google Chrome
RUN add-apt-repository ppa:xtradeb/apps -y && \
    apt-get update && \
    apt-get install -y chromium  --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Chinese fonts and language support
RUN apt-get update && apt-get install -y \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    language-pack-zh-hans \
    locales \
    && locale-gen zh_CN.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set default locale
#ENV LANG=zh_CN.UTF-8 \
#    LANGUAGE=zh_CN:zh \
#    LC_ALL=zh_CN.UTF-8

# Set working directory
WORKDIR /app

# Copy project files (copy dependency files first to leverage cache)
COPY sandbox/pyproject.toml ./

# Install Python dependencies
RUN uv sync --no-dev

# Copy remaining sandbox files
COPY sandbox/ ./

# Ensure application files are writable by app user
RUN chown -R ubuntu:ubuntu /app

# Configure supervisor
COPY sandbox/supervisord.conf /etc/supervisor/conf.d/app.conf

# Helix-managed dev server runner. Owned by supervisord, not the agent —
# this is the "service that's always running when project files exist"
# guarantee. See sandbox/helix-dev-runner.sh for stack detection logic.
COPY sandbox/helix-dev-runner.sh /usr/local/bin/helix-dev-runner.sh
RUN chmod +x /usr/local/bin/helix-dev-runner.sh

# Install helixcli — deterministic project scaffolder the agent calls via
# the `helix_scaffold` tool. Installed into a world-readable venv at
# /opt/helixcli-venv so both root and the ubuntu user can invoke it via
# the /usr/local/bin/helixcli symlink. (uv tool install would land the
# binary under /root/.local/bin which ubuntu can't read.)
COPY helixcli /tmp/helixcli
RUN uv venv --python python3.10 /opt/helixcli-venv && \
    uv pip install --python /opt/helixcli-venv/bin/python /tmp/helixcli && \
    ln -sf /opt/helixcli-venv/bin/helixcli /usr/local/bin/helixcli && \
    chmod -R a+rX /opt/helixcli-venv && \
    rm -rf /tmp/helixcli

# Expose ports
EXPOSE 8080 9222 5900 5901

ENV UVI_ARGS=""
ENV CHROME_ARGS=""

# Use supervisor to start all services
CMD ["supervisord", "-n", "-c", "/app/supervisord.conf"] 
