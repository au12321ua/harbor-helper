# Test base image for OpenCode tasks: Node through nvm and OpenCode at the version the
# Runner pins (maestro_runner.agents.OPENCODE_VERSION), where Harbor's OpenCode agent
# looks for them, so trials skip the install. Build once, through a proxy if needed:
#   docker build --build-arg HTTPS_PROXY=... -t maestro-test/ubuntu-opencode:22.04 .
FROM maestro-test/ubuntu-tmux:22.04
ARG OPENCODE_VERSION=1.18.35
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
ENV NVM_DIR=/root/.nvm
RUN curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" && nvm install 22 && nvm alias default 22 \
    && npm i -g "opencode-ai@${OPENCODE_VERSION}" && opencode --version
