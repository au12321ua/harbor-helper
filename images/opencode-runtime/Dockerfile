ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG OPENCODE_VERSION

# Install once at maintenance time, without any endpoint or credential.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl bash coreutils nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "opencode-ai@${OPENCODE_VERSION}" \
    && test "$(opencode --version)" = "${OPENCODE_VERSION}"
