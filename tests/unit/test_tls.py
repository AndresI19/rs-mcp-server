"""Unit tests for tls.py — conditional TLS resolution (issue #21)."""
import ssl

import pytest

from rs_mcp_server import tls


def _write_pair(directory, cert_name, key_name):
    """Write a real self-signed cert/key pair into `directory` under the given names."""
    generated = tls._generate_self_signed(out_dir=str(directory / "_gen"))
    cert_bytes = open(generated["ssl_certfile"], "rb").read()
    key_bytes = open(generated["ssl_keyfile"], "rb").read()
    (directory / cert_name).write_bytes(cert_bytes)
    (directory / key_name).write_bytes(key_bytes)


class TestResolveUvicornTls:
    def test_missing_dir_serves_http(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_TLS_DIR", str(tmp_path / "absent"))
        assert tls.resolve_uvicorn_tls() == {}

    def test_empty_dir_generates_self_signed(self, tmp_path, monkeypatch):
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        monkeypatch.setenv("MCP_TLS_DIR", str(cert_dir))

        result = tls.resolve_uvicorn_tls()

        assert set(result) == {"ssl_certfile", "ssl_keyfile"}
        # Generated cert must load into an SSL context — i.e. it's a valid cert/key pair.
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(result["ssl_certfile"], result["ssl_keyfile"])

    @pytest.mark.parametrize(
        "cert_name,key_name",
        [("tls.crt", "tls.key"), ("fullchain.pem", "privkey.pem"), ("cert.pem", "key.pem")],
    )
    def test_existing_pair_is_used(self, tmp_path, monkeypatch, cert_name, key_name):
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        _write_pair(cert_dir, cert_name, key_name)
        monkeypatch.setenv("MCP_TLS_DIR", str(cert_dir))

        result = tls.resolve_uvicorn_tls()

        assert result == {
            "ssl_certfile": str(cert_dir / cert_name),
            "ssl_keyfile": str(cert_dir / key_name),
        }

    def test_pair_priority_order(self, tmp_path, monkeypatch):
        # When multiple conventions are present, tls.crt/tls.key wins.
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        _write_pair(cert_dir, "tls.crt", "tls.key")
        _write_pair(cert_dir, "cert.pem", "key.pem")
        monkeypatch.setenv("MCP_TLS_DIR", str(cert_dir))

        result = tls.resolve_uvicorn_tls()

        assert result["ssl_certfile"] == str(cert_dir / "tls.crt")

    def test_cert_without_key_falls_back_to_self_signed(self, tmp_path, monkeypatch):
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        (cert_dir / "tls.crt").write_text("not a real key's partner")
        monkeypatch.setenv("MCP_TLS_DIR", str(cert_dir))

        result = tls.resolve_uvicorn_tls()

        # No complete pair → self-signed fallback under /tmp, not the orphaned cert.
        assert result["ssl_certfile"] != str(cert_dir / "tls.crt")
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(result["ssl_certfile"], result["ssl_keyfile"])


class TestGenerateSelfSigned:
    def test_writes_loadable_pair(self, tmp_path):
        result = tls._generate_self_signed(out_dir=str(tmp_path / "ss"))
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(result["ssl_certfile"], result["ssl_keyfile"])
