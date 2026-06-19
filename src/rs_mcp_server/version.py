"""Version metadata for the running server — exposed via the /version endpoint."""
import os
import subprocess
from pathlib import Path

# Sibling file written by the Dockerfile (or any deploy step) using the latest
# git tag from #81's auto-tag action. Absent in dev checkouts → "snapshot".
_VERSION_FILE = Path(__file__).parent / "VERSION"


def _read_git_sha() -> str | None:
    sha = os.environ.get("MCP_GIT_SHA", "").strip()
    if sha:
        return sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=2.0,
        )
        return result.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _read_version() -> str:
    try:
        value = _VERSION_FILE.read_text().strip()
    except (FileNotFoundError, OSError):
        return "snapshot"
    return value or "snapshot"


def _build_info() -> dict:
    info: dict = {"version": _read_version()}
    sha = _read_git_sha()
    if sha:
        info["git_sha"] = sha
    build_date = os.environ.get("MCP_BUILD_DATE", "").strip()
    if build_date:
        info["build_date"] = build_date
    return info


VERSION_INFO: dict = _build_info()
