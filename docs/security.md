# Security posture — rs-mcp-server

## Threat model

The container is designed to make a compromise of the MCP server itself non-fatal — an attacker who lands code execution inside the process should find no privileged Linux capabilities, a read-only filesystem outside `/tmp` and `/logs`, and a low-privilege UID with no way to escalate. Compromise of the Docker daemon or host kernel is **out of scope** — those are the responsibility of whoever operates the deployment target.

## Runtime posture

| Control | Setting |
|---------|---------|
| User | `mcp-server` (uid 10001), non-root, no login shell, no home dir |
| Filesystem | `--read-only` rootfs · `/tmp` tmpfs (16m) · `/logs` named volume |
| Capabilities | `--cap-drop=ALL` (no Linux capabilities granted) |
| Privilege escalation | `--security-opt no-new-privileges:true` |
| Memory limit | 512 MB |
| PID limit | 100 |
| Healthcheck | `curl /health` every 30s |

All flags live in `scripts/docker.sh`; the K8s analogs are documented at the bottom of this doc.

## Scanner policy

The `image-scan` job in `.github/workflows/test.yml` runs [Trivy](https://github.com/aquasecurity/trivy) on every PR and push to `main`. The gate **fails on `HIGH` or `CRITICAL`** severities and ignores unfixed CVEs (`ignore-unfixed: true`) — there is no value in blocking on vulnerabilities upstream has not yet shipped a fix for. The Trivy action is pinned by commit SHA, not tag, so an upstream tag re-point cannot silently change scan behavior.

## Known residual risks

- **Cache exhaustion.** `cache.py` is an in-memory dict with TTL eviction only. An attacker spamming unique cache keys can grow memory; the 512 MB cap bounds the damage but does not prevent slowdown. Rate-limiting is deferred to the reverse proxy ([#21](https://github.com/AndresI19/RS-Agent-Planning/issues/21)).
- **No image signing.** cosign/Sigstore signing is deferred until we publish to a registry.
- **No SBOM.** The Trivy report is the closest equivalent; Syft can be added when the publish pipeline lands.
- **Local dev runtime (Colima/qemu).** Not part of the production threat model; the hardening flags still apply but the VM layer is the user's responsibility.
- **First-time volume migration.** Existing `rs-mcp-server-logs` volumes from before this PR are root-owned. Run `bash scripts/docker.sh clean && make start` once to reset the volume so it picks up mcp-server ownership from the Dockerfile-built `/logs`.

## K8s mapping

Every flag here has a direct `securityContext` analog when this moves to K8s:

| docker.sh | Pod / container `securityContext` |
|-----------|-----------------------------------|
| `--read-only` | `readOnlyRootFilesystem: true` |
| `--cap-drop=ALL` | `capabilities.drop: [ALL]` |
| image-default user | `runAsUser: 10001`, `runAsNonRoot: true` |
| `--security-opt no-new-privileges:true` | `allowPrivilegeEscalation: false` |
| `--memory 512m`, `--pids-limit 100` | `resources.limits.memory` / `resources.limits.pids` |
| HEALTHCHECK | `livenessProbe` / `readinessProbe` against `/health` |

The hardening here is forward-compatible with the future deployment story (Epic [#5](https://github.com/AndresI19/RS-Agent-Planning/issues/5)).
