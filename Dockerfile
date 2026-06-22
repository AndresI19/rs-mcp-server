# syntax=docker/dockerfile:1.6

# Builder needs the full image (compilers, dev headers) to build the venv.
ARG BASE_IMAGE=registry.access.redhat.com/ubi9/python-312:latest
# Runtime only executes Python, so it uses the minimal UBI base (~1GB smaller).
ARG RUNTIME_IMAGE=registry.access.redhat.com/ubi9/python-312-minimal:latest

FROM ${BASE_IMAGE} AS builder

USER 0
ENV VIRTUAL_ENV=/opt/venv \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN --mount=type=bind,source=requirements.txt,target=/build/requirements.txt \
    pip install --require-hashes -r /build/requirements.txt

RUN --mount=type=bind,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,source=src,target=/src/src \
    cp -r /src /tmp/build \
    && rm -rf /tmp/build/src/*.egg-info \
    && pip install --no-deps /tmp/build \
    && rm -rf /tmp/build


FROM ${RUNTIME_IMAGE} AS runtime

ARG VERSION
ARG GIT_SHA
ARG BUILD_DATE

LABEL org.opencontainers.image.title="rs-mcp-server" \
      org.opencontainers.image.description="MCP server exposing RuneScape research tools to Claude Desktop" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/AndresI19/rs-mcp-server" \
      org.opencontainers.image.licenses="MIT"

USER 0
# The minimal base omits shadow-utils (useradd); install it and drop the dnf cache
# in the same layer so the image stays slim.
RUN microdnf install -y shadow-utils \
 && microdnf clean all \
 && useradd --uid 10001 --shell /sbin/nologin --no-create-home --user-group mcp-server \
 && mkdir -p /logs \
 && chown mcp-server:mcp-server /logs

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder --chown=mcp-server:mcp-server ${VIRTUAL_ENV} ${VIRTUAL_ENV}
COPY --chmod=755 docker/bin/start-server /usr/local/bin/start-server

USER mcp-server
EXPOSE 8000

# Protocol-tolerant: the same port serves HTTP or (when /etc/tls_certs is mounted) HTTPS.
# Try https first (-k tolerates the self-signed fallback cert), then fall back to http.
HEALTHCHECK --interval=5m --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsSk https://localhost:8000/health || curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["start-server", "--start"]
