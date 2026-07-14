from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import ConfigDict, StringConstraints

FROZEN_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
)

MUTABLE_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    str_strip_whitespace=True,
)

Sha256Hex = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-f0-9]{64}$",
        min_length=64,
        max_length=64,
    ),
]

VersionString = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}$",
        min_length=1,
        max_length=128,
    ),
]

OpaqueObjectKey = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9/_\-.]{0,511}$",
        min_length=1,
        max_length=512,
    ),
]


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
