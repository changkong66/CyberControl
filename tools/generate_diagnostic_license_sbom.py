from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

JEMALLOC_VERSION = "5.3.0"
JEMALLOC_SOURCE_SHA256 = "2db82d1e7119df3e71b7640219b6dfe84789bc0537983c3b7ac4f7189aecfeaa"
JEMALLOC_LICENSE_SHA256 = "94aa2caa98c25d942f58b956c71dba6a99ff98fc3a31cbc669fe2a4cd0268b53"
LIBRARY_NAME = "libjemalloc.so.2"
BUILD_ID_PATTERN = re.compile(r"\bBuild ID:\s*([0-9a-f]{40})\b")
SHA256_PATTERN = re.compile(r"\b([0-9a-f]{64})\b")


def _read_library_sha256(provenance: Path) -> str:
    document = (provenance / "library-sha256.txt").read_text(encoding="utf-8")
    match = SHA256_PATTERN.search(document)
    if match is None:
        raise ValueError("library-sha256.txt does not contain a SHA256")
    return match.group(1)


def _read_build_id(provenance: Path) -> str:
    document = (provenance / "library-notes.txt").read_text(encoding="utf-8")
    match = BUILD_ID_PATTERN.search(document)
    if match is None:
        raise ValueError("library-notes.txt does not contain an ELF build ID")
    return match.group(1)


def _verify_input_source(provenance: Path) -> None:
    document = (provenance / "input-sha256.txt").read_text(encoding="utf-8")
    if not document.startswith(f"{JEMALLOC_SOURCE_SHA256}  "):
        raise ValueError("build provenance is not bound to jemalloc 5.3.0 source")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_bom(provenance: Path, licenses: Path) -> dict[str, object]:
    _verify_input_source(provenance)
    license_path = licenses / "jemalloc" / "COPYING"
    if _sha256(license_path) != JEMALLOC_LICENSE_SHA256:
        raise ValueError("jemalloc COPYING SHA256 is not approved")
    library_sha256 = _read_library_sha256(provenance)
    build_id = _read_build_id(provenance)
    bom_ref = f"pkg:generic/jemalloc@{JEMALLOC_VERSION}"
    component = {
        "type": "library",
        "bom-ref": bom_ref,
        "name": "jemalloc",
        "version": JEMALLOC_VERSION,
        "purl": bom_ref,
        "licenses": [{"license": {"id": "BSD-2-Clause"}}],
        "hashes": [{"alg": "SHA-256", "content": library_sha256}],
        "properties": [
            {
                "name": "cybercontrol:library-path",
                "value": f"/opt/cybercontrol/jemalloc-prof/lib/{LIBRARY_NAME}",
            },
            {"name": "cybercontrol:library-build-id", "value": build_id},
            {
                "name": "cybercontrol:license-evidence",
                "value": "/opt/cybercontrol/jemalloc-prof/share/licenses/jemalloc/COPYING",
            },
            {"name": "cybercontrol:source-sha256", "value": JEMALLOC_SOURCE_SHA256},
        ],
        "externalReferences": [
            {
                "type": "vcs",
                "url": "https://github.com/jemalloc/jemalloc",
            }
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(component, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, fingerprint)}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "cybercontrol-jemalloc-profile-capability",
                "version": JEMALLOC_VERSION,
            },
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "cybercontrol-diagnostic-license-sbom",
                        "version": "1.0.0",
                    }
                ]
            },
        },
        "components": [component],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a license SBOM for the source-built diagnostic component"
    )
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    document = build_bom(arguments.provenance, arguments.licenses)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
