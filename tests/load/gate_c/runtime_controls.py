from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_POOL_TIMEOUT = re.compile(
    r"(?:QueuePool\s+limit.*connection\s+timed\s+out|"
    r"sqlalchemy(?:\.exc)?\.TimeoutError.*(?:pool|connection)|"
    r"(?:database|connection)\s+pool.*(?:acquisition|checkout).*timeout)",
    re.IGNORECASE,
)
_BAD_ADDRESS = re.compile(r"\bBad address\b", re.IGNORECASE)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract redacted Gate C runtime controls.")
    parser.add_argument("--api-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def summarize_api_log(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    lines = content.decode("utf-8", errors="replace").splitlines()
    matches = [line.strip() for line in lines if _POOL_TIMEOUT.search(line)]
    bad_address_matches = [line.strip() for line in lines if _BAD_ADDRESS.search(line)]
    return {
        "schema_version": "cybercontrol.gate-c-runtime-controls.v1",
        "api_log_bytes": len(content),
        "api_log_sha256": hashlib.sha256(content).hexdigest(),
        "database_pool_acquisition_timeout_count": len(matches),
        "database_pool_acquisition_timeout_line_sha256": [
            hashlib.sha256(line.encode("utf-8")).hexdigest() for line in matches
        ],
        "bad_address_count": len(bad_address_matches),
        "bad_address_line_sha256": [
            hashlib.sha256(line.encode("utf-8")).hexdigest() for line in bad_address_matches
        ],
        "passed": not matches and not bad_address_matches,
    }


def main() -> int:
    args = _parser().parse_args()
    document = summarize_api_log(args.api_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": document["passed"], "output": str(args.output)}, sort_keys=True))
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
