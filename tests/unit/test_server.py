"""Sanity tests for the Starlette server: /health success and /health?crash termination (issue #27)."""
import subprocess
import sys
import time

import httpx
import pytest


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        from starlette.testclient import TestClient

        from rs_mcp_server.server import web

        client = TestClient(web)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestHealthCrash:
    def test_crash_terminates_server_and_logs_traceback(self, tmp_path):
        log_file = tmp_path / "server.log"
        port = 18765

        with open(log_file, "wb") as fh:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn",
                    "rs_mcp_server.server:web",
                    "--host", "127.0.0.1",
                    "--port", str(port),
                ],
                stdout=fh,
                stderr=subprocess.STDOUT,
            )

        try:
            # Poll for the server to become healthy (up to 10 seconds)
            for _ in range(20):
                try:
                    r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
                    if r.status_code == 200:
                        break
                except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError):
                    pass
                time.sleep(0.5)
            else:
                pytest.fail("Server did not become healthy within 10 seconds")

            # Trigger the crash. The response may or may not return cleanly
            # before the daemon thread terminates the process.
            try:
                httpx.get(f"http://127.0.0.1:{port}/health?crash", timeout=2.0)
            except (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
                httpx.TimeoutException,
            ):
                pass

            # Server should terminate via os._exit(1) inside _thread_excepthook.
            exit_code = proc.wait(timeout=10)
            assert exit_code != 0, f"Server should exit non-zero on crash, got {exit_code}"

            log_content = log_file.read_text(errors="replace")
            assert "Server terminated" in log_content
            assert "RuntimeError" in log_content
            assert "deliberate crash via /health?crash" in log_content
        finally:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
