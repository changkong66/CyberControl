from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PROCESS_VERSION = "Gate-C-12-v2.0"


def _certificate_sha256(certificate: x509.Certificate) -> str:
    return hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()


def _write_new(path: Path, content: bytes, mode: int) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(mode)


def generate_tls_material(output_directory: Path, server_hostname: str) -> dict[str, object]:
    if not server_hostname or server_hostname != server_hostname.strip():
        raise ValueError("TLS server hostname is invalid")
    output_directory = output_directory.resolve(strict=True)
    if not output_directory.is_dir() or output_directory.is_symlink():
        raise ValueError("TLS output directory must be a real existing directory")
    paths = {
        "ca": output_directory / "ca.crt",
        "server": output_directory / "server.crt",
        "key": output_directory / "server.key",
        "manifest": output_directory / "tls-manifest.json",
    }
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("TLS material already exists")

    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "CyberControl Gate C Ephemeral CA")]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=24))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                key_cert_sign=True,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, server_hostname)])
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=24))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(server_hostname)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_new(paths["ca"], ca_certificate.public_bytes(serialization.Encoding.PEM), 0o644)
    _write_new(paths["server"], server_certificate.public_bytes(serialization.Encoding.PEM), 0o644)
    _write_new(
        paths["key"],
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        0o600,
    )
    manifest = {
        "schema_version": "cybercontrol.gate-c-calibration-tls.v1",
        "process_version": PROCESS_VERSION,
        "classification": "NON_ACCEPTANCE_DIAGNOSTIC",
        "server_hostname": server_hostname,
        "generated_at_utc": now.isoformat(),
        "not_valid_before_utc": server_certificate.not_valid_before_utc.isoformat(),
        "not_valid_after_utc": server_certificate.not_valid_after_utc.isoformat(),
        "ca_certificate_sha256": _certificate_sha256(ca_certificate),
        "server_certificate_sha256": _certificate_sha256(server_certificate),
        "ca_private_key_persisted": False,
        "server_private_key_recorded_in_evidence": False,
        "minimum_tls_version": ssl.TLSVersion.TLSv1_2.name,
    }
    _write_new(
        paths["manifest"],
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        0o644,
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate one ephemeral ADR-0033 PostgreSQL TLS identity."
    )
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--server-hostname", default="postgres")
    arguments = parser.parse_args()
    generate_tls_material(arguments.output_directory, arguments.server_hostname)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
