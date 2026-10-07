ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git ripgrep \
    libgl1 libglu1-mesa libx11-6 libxext6 libxrender1 libxinerama1 \
    libxrandr2 libxcursor1 libxi6 libsm6 libice6 libfontconfig1 libosmesa6 \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/cad-venv
ENV PATH="/opt/cad-venv/bin:${PATH}" \
    VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow \
    PYTHONUNBUFFERED=1
COPY cadir /opt/simplecadapi
# CADIR's transitive ranges are resolved at build time; retain provenance.
RUN python -m pip install --no-cache-dir /opt/simplecadapi PyYAML==6.0.2 \
    && python -m pip freeze --all > /opt/cad-runtime-pip-freeze.txt
COPY cadir/docs/skill /skills/simplecadapi
WORKDIR /workspace
