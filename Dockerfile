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

# Cache-bust the package install below on every commit. The runtime stage stamps VERSION and the
# revision label from build-args, independently of what this stage installed into the venv — so a
# reused install layer would ship OLD code under a FRESH version and revision, an image that labels
# itself correct while running the previous release (this happened to home at 0.1.42). Referencing
# GIT_SHA in a RUN here ties the source-install layer's cache key to the commit; the requirements
# install above (the slow one) stays cached.
ARG GIT_SHA
RUN echo "build stage source commit: ${GIT_SHA:-unknown}"

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

# Stamp the version, which version.py serves from /version. It reads a VERSION file SIBLING TO ITSELF
# (Path(__file__).parent / "VERSION"), so this cannot just drop a file in /app — it has to land inside
# the installed package. The package lives somewhere in the venv's site-packages, whose path embeds
# the Python minor version, so the location is asked of the package itself rather than hard-coded: a
# 3.12 → 3.13 base bump would silently break a hardcoded path, and the failure would be a server
# quietly reporting "snapshot" forever, which is exactly the bug this endpoint exists to prevent.
# An unset VERSION (a bare `docker build`) writes an empty file, and version.py falls back to
# "snapshot" on its own.
RUN printf '%s' "${VERSION}" \
      > "$(python -c 'import pathlib, rs_mcp_server; print(pathlib.Path(rs_mcp_server.__file__).parent)')/VERSION"

USER mcp-server
# The listen address is the IMAGE's decision, not the entrypoint's: a container exists to be reached
# from outside itself, so it binds every interface. The library default stays 127.0.0.1, because a
# dev server that opens itself to the network the moment you run it is a surprise, not a convenience.
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

# Protocol-tolerant: the same port serves HTTP or (when /etc/tls_certs is mounted) HTTPS.
# Try https first (-k tolerates the self-signed fallback cert), then fall back to http.
HEALTHCHECK --interval=5m --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsSk https://localhost:8000/health || curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["start-server", "--start"]
