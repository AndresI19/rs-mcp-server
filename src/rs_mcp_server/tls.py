"""Conditional TLS resolution for the MCP server's uvicorn listener.

The HTTP/HTTPS decision is keyed on a cert directory (``/etc/tls_certs`` by default,
overridable via ``MCP_TLS_DIR`` for tests). The directory is populated at deploy time by
volume-mounting host certs into the container:

* directory absent                  -> serve plain HTTP (return ``{}``)
* directory present, no usable pair  -> generate a self-signed cert, serve HTTPS
* directory present, cert/key pair   -> serve HTTPS with those certs

The returned dict is splatted straight into ``uvicorn.run(...)``.
"""
import datetime
import ipaddress
import logging
import os

_LOGGER = logging.getLogger("rs_mcp_server.tls")

_DEFAULT_CERT_DIR = "/etc/tls_certs"
_SELF_SIGNED_DIR = "/tmp/tls_selfsigned"

# (cert filename, key filename) pairs in priority order. First pair where both files
# exist wins. Covers the k8s TLS-secret, Let's Encrypt, and generic-PEM conventions.
_CERT_PAIRS = (
    ("tls.crt", "tls.key"),
    ("fullchain.pem", "privkey.pem"),
    ("cert.pem", "key.pem"),
)


def _cert_dir() -> str:
    return os.environ.get("MCP_TLS_DIR", _DEFAULT_CERT_DIR)


def _find_cert_pair(cert_dir: str) -> dict | None:
    """Return ssl kwargs for the first complete cert/key pair found, else ``None``."""
    for cert_name, key_name in _CERT_PAIRS:
        cert_path = os.path.join(cert_dir, cert_name)
        key_path = os.path.join(cert_dir, key_name)
        if os.path.isfile(cert_path) and os.path.isfile(key_path):
            return {"ssl_certfile": cert_path, "ssl_keyfile": key_path}
    return None


def _generate_self_signed(out_dir: str = _SELF_SIGNED_DIR) -> dict:
    """Mint a 1-year self-signed localhost cert into ``out_dir`` and return ssl kwargs.

    Written under /tmp because the container rootfs is read-only and the cert dir is
    mounted ``:ro`` — /tmp (tmpfs) is the only writable path at runtime.
    """
    # Imported lazily so the HTTP path never pays the cryptography import cost.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    os.makedirs(out_dir, exist_ok=True)
    cert_path = os.path.join(out_dir, "cert.pem")
    key_path = os.path.join(out_dir, "key.pem")
    with open(cert_path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as fh:
        fh.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    os.chmod(key_path, 0o600)
    return {"ssl_certfile": cert_path, "ssl_keyfile": key_path}


def resolve_uvicorn_tls() -> dict:
    """Resolve uvicorn ssl kwargs from the cert directory. ``{}`` means serve HTTP."""
    cert_dir = _cert_dir()
    if not os.path.isdir(cert_dir):
        _LOGGER.info("TLS disabled — no cert dir at %s; serving HTTP", cert_dir)
        return {}

    pair = _find_cert_pair(cert_dir)
    if pair is not None:
        _LOGGER.info("TLS enabled — using cert %s", pair["ssl_certfile"])
        return pair

    _LOGGER.warning(
        "TLS cert dir %s exists but holds no usable cert/key pair; "
        "generating a self-signed certificate. If you mounted real certs, check that a "
        "recognised pair (tls.crt/tls.key, fullchain.pem/privkey.pem, or cert.pem/key.pem) "
        "is present and readable by the server user (uid 10001).",
        cert_dir,
    )
    pair = _generate_self_signed()
    _LOGGER.info("TLS enabled — using self-signed cert %s", pair["ssl_certfile"])
    return pair
