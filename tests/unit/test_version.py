"""Tests for the version helper module and /version endpoint (issue #80)."""
from rs_mcp_server import version as version_mod


class TestReadVersion:
    def test_reads_version_from_file(self, tmp_path, monkeypatch):
        version_file = tmp_path / "VERSION"
        version_file.write_text("v0.1.7\n")
        monkeypatch.setattr(version_mod, "_VERSION_FILE", version_file)
        assert version_mod._read_version() == "v0.1.7"

    def test_returns_snapshot_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_mod, "_VERSION_FILE", tmp_path / "no-such-file")
        assert version_mod._read_version() == "snapshot"

    def test_returns_snapshot_when_file_empty(self, tmp_path, monkeypatch):
        version_file = tmp_path / "VERSION"
        version_file.write_text("   \n")
        monkeypatch.setattr(version_mod, "_VERSION_FILE", version_file)
        assert version_mod._read_version() == "snapshot"

    def test_returns_snapshot_when_file_unreadable(self, tmp_path, monkeypatch):
        # Point at a directory instead of a file → OSError on read_text()
        monkeypatch.setattr(version_mod, "_VERSION_FILE", tmp_path)
        assert version_mod._read_version() == "snapshot"


class TestVersionEndpoint:
    def test_returns_version_info_as_json(self):
        from starlette.testclient import TestClient

        from rs_mcp_server.server import web

        client = TestClient(web)
        response = client.get("/version")
        assert response.status_code == 200
        body = response.json()
        assert body == version_mod.VERSION_INFO
        assert "version" in body
