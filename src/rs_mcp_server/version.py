"""Version metadata for the running server — exposed via the /version endpoint."""
from pathlib import Path

# Sibling file written by the deploy step (typically the Dockerfile) using the
# latest git tag from #81's auto-tag action. Absent in dev checkouts → "snapshot".
_VERSION_FILE = Path(__file__).parent / "VERSION"


def _read_version() -> str:
    try:
        value = _VERSION_FILE.read_text().strip()
    except (FileNotFoundError, OSError):
        return "snapshot"
    return value or "snapshot"


VERSION_INFO: dict = {"version": _read_version()}
