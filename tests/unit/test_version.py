"""Tests for the version helper module and /version endpoint (issue #80)."""
import pytest

from rs_mcp_server import version as version_mod


@pytest.fixture
def _clean_env(monkeypatch):
    monkeypatch.delenv("MCP_GIT_SHA", raising=False)
    monkeypatch.delenv("MCP_BUILD_DATE", raising=False)


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


class TestReadGitSha:
    def test_env_var_takes_priority(self, _clean_env, monkeypatch):
        monkeypatch.setenv("MCP_GIT_SHA", "abc1234")
        # subprocess.run should never be called when env is set
        def boom(*a, **kw):
            raise AssertionError("subprocess.run should not be invoked when env is set")
        monkeypatch.setattr(version_mod.subprocess, "run", boom)
        assert version_mod._read_git_sha() == "abc1234"

    def test_subprocess_used_when_env_unset(self, _clean_env, monkeypatch):
        class FakeResult:
            stdout = "deadbee\n"
        monkeypatch.setattr(version_mod.subprocess, "run", lambda *a, **kw: FakeResult())
        assert version_mod._read_git_sha() == "deadbee"

    def test_returns_none_when_git_missing(self, _clean_env, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("git")
        monkeypatch.setattr(version_mod.subprocess, "run", raise_fnf)
        assert version_mod._read_git_sha() is None

    def test_returns_none_when_subprocess_errors(self, _clean_env, monkeypatch):
        import subprocess as sp
        def raise_called(*a, **kw):
            raise sp.CalledProcessError(128, ["git"])
        monkeypatch.setattr(version_mod.subprocess, "run", raise_called)
        assert version_mod._read_git_sha() is None


class TestBuildInfo:
    def test_includes_only_version_when_no_extras(self, _clean_env, monkeypatch):
        monkeypatch.setattr(version_mod, "_read_version", lambda: "1.2.3")
        monkeypatch.setattr(version_mod, "_read_git_sha", lambda: None)
        info = version_mod._build_info()
        assert info == {"version": "1.2.3"}

    def test_includes_git_sha_when_available(self, _clean_env, monkeypatch):
        monkeypatch.setattr(version_mod, "_read_version", lambda: "1.2.3")
        monkeypatch.setattr(version_mod, "_read_git_sha", lambda: "abc1234")
        info = version_mod._build_info()
        assert info == {"version": "1.2.3", "git_sha": "abc1234"}

    def test_includes_build_date_when_env_set(self, _clean_env, monkeypatch):
        monkeypatch.setattr(version_mod, "_read_version", lambda: "1.2.3")
        monkeypatch.setattr(version_mod, "_read_git_sha", lambda: None)
        monkeypatch.setenv("MCP_BUILD_DATE", "2026-06-19T12:00:00Z")
        info = version_mod._build_info()
        assert info == {"version": "1.2.3", "build_date": "2026-06-19T12:00:00Z"}

    def test_omits_blank_env_values(self, _clean_env, monkeypatch):
        monkeypatch.setattr(version_mod, "_read_version", lambda: "1.2.3")
        monkeypatch.setattr(version_mod, "_read_git_sha", lambda: None)
        monkeypatch.setenv("MCP_BUILD_DATE", "   ")
        info = version_mod._build_info()
        assert "build_date" not in info


class TestVersionEndpoint:
    def test_returns_version_info_as_json(self):
        from starlette.testclient import TestClient

        from rs_mcp_server.server import web

        client = TestClient(web)
        response = client.get("/version")
        assert response.status_code == 200
        body = response.json()
        assert "version" in body
        # VERSION_INFO is computed at module import — body should equal it exactly
        assert body == version_mod.VERSION_INFO
