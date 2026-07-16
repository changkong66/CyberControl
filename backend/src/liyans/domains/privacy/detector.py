from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c10 import PIIType, PrivacyAction


@dataclass(frozen=True, slots=True)
class PIIMatch:
    pii_type: PIIType
    block_id: str
    json_pointer: str
    original_value_sha256: str
    confidence: float
    action: PrivacyAction
    replacement: str
    reason_code: str


_EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_NATIONAL_ID = re.compile(
    r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)"
)

_KEY_TYPE: tuple[tuple[PIIType, frozenset[str], str], ...] = (
    (
        PIIType.CREDENTIAL,
        frozenset({"password", "passwd", "api_key", "apikey", "access_token", "secret"}),
        "C10_CREDENTIAL_FIELD",
    ),
    (
        PIIType.BIOMETRIC,
        frozenset({"biometric", "face_id", "fingerprint", "iris"}),
        "C10_BIOMETRIC_FIELD",
    ),
    (
        PIIType.NATIONAL_ID,
        frozenset({"national_id", "id_card", "身份证", "identity_number"}),
        "C10_NATIONAL_ID_FIELD",
    ),
    (PIIType.STUDENT_ID, frozenset({"student_id", "learner_id"}), "C10_STUDENT_ID_FIELD"),
    (PIIType.NAME, frozenset({"name", "student_name", "real_name"}), "C10_NAME_FIELD"),
    (
        PIIType.ADDRESS,
        frozenset({"address", "home_address", "postal_address"}),
        "C10_ADDRESS_FIELD",
    ),
)


class DeterministicPIIDetector:
    """Detect PII locally and return only replacement-safe metadata."""

    detector_version = "c10-deterministic-pii-v1"

    def __init__(
        self,
        *,
        max_matches: int = 256,
        max_string_length: int = 32_768,
        tokenize_types: frozenset[PIIType] | None = None,
    ) -> None:
        if not 1 <= max_matches <= 4096:
            raise ValueError("max_matches must be between 1 and 4096")
        if not 1 <= max_string_length <= 1_000_000:
            raise ValueError("max_string_length must be between 1 and 1000000")
        self._max_matches = max_matches
        self._max_string_length = max_string_length
        self._tokenize_types = tokenize_types or frozenset(
            {PIIType.EMAIL, PIIType.PHONE, PIIType.STUDENT_ID}
        )

    def scan(self, candidate: Any) -> tuple[PIIMatch, ...]:
        matches: list[PIIMatch] = []
        for block in candidate.blocks:
            for path, key, value in self._walk(block.content, f"/blocks/{block.ordinal}/content"):
                if len(matches) >= self._max_matches:
                    return tuple(matches)
                if not isinstance(value, str):
                    continue
                matches.extend(self._scan_value(block.block_id, path, key, value))
        unique: dict[tuple[str, PIIType, str], PIIMatch] = {}
        for match in matches:
            unique.setdefault(
                (match.json_pointer, match.pii_type, match.original_value_sha256), match
            )
        return tuple(unique.values())[: self._max_matches]

    def _scan_value(self, block_id: str, path: str, key: str | None, value: str) -> list[PIIMatch]:
        text = value[: self._max_string_length]
        normalized_key = (key or "").casefold().replace("-", "_").replace(" ", "_")
        for pii_type, keys, reason_code in _KEY_TYPE:
            if normalized_key in keys and text.strip():
                return [self._match(block_id, path, pii_type, text, reason_code, True)]

        patterns = (
            (PIIType.NATIONAL_ID, _NATIONAL_ID, "C10_NATIONAL_ID_PATTERN"),
            (PIIType.EMAIL, _EMAIL, "C10_EMAIL_PATTERN"),
            (PIIType.PHONE, _PHONE, "C10_PHONE_PATTERN"),
        )
        output: list[PIIMatch] = []
        for pii_type, pattern, reason_code in patterns:
            found = pattern.search(text)
            if found is None:
                continue
            matched = found.group(0)
            output.append(self._match(block_id, path, pii_type, matched, reason_code, False))
        return output

    def _match(
        self,
        block_id: str,
        path: str,
        pii_type: PIIType,
        value: str,
        reason_code: str,
        replace_entire: bool,
    ) -> PIIMatch:
        original_hash = canonical_sha256(value)
        action = self._action(pii_type)
        if action == PrivacyAction.TOKENIZE:
            replacement = "tok_" + original_hash[:32]
        elif action == PrivacyAction.BLOCK:
            replacement = f"[BLOCKED:{pii_type.value}]"
        else:
            replacement = f"[REDACTED:{pii_type.value}]"
        if not replace_entire and action != PrivacyAction.BLOCK:
            replacement = (
                f"[REDACTED:{pii_type.value}]" if action == PrivacyAction.REDACT else replacement
            )
        return PIIMatch(
            pii_type=pii_type,
            block_id=block_id,
            json_pointer=path,
            original_value_sha256=original_hash,
            confidence=0.99 if replace_entire else 0.96,
            action=action,
            replacement=replacement,
            reason_code=reason_code,
        )

    @staticmethod
    def _action(pii_type: PIIType) -> PrivacyAction:
        if pii_type in {PIIType.NATIONAL_ID, PIIType.BIOMETRIC, PIIType.CREDENTIAL}:
            return PrivacyAction.BLOCK
        if pii_type in {PIIType.EMAIL, PIIType.PHONE, PIIType.STUDENT_ID}:
            return PrivacyAction.TOKENIZE
        return PrivacyAction.REDACT

    @classmethod
    def _walk(
        cls, value: Any, path: str, key: str | None = None
    ) -> list[tuple[str, str | None, Any]]:
        if isinstance(value, dict):
            output: list[tuple[str, str | None, Any]] = []
            for child_key, child in value.items():
                escaped = str(child_key).replace("~", "~0").replace("/", "~1")
                output.extend(cls._walk(child, f"{path}/{escaped}", str(child_key)))
            return output
        if isinstance(value, list):
            output = []
            for index, child in enumerate(value):
                output.extend(cls._walk(child, f"{path}/{index}", key))
            return output
        return [(path, key, value)]


def replace_json_pointer(value: Any, pointer: str, replacement: str) -> Any:
    """Return a copy with one exact JSON pointer replaced."""

    parts = pointer.lstrip("/").split("/") if pointer != "/" else []
    parts = [part.replace("~1", "/").replace("~0", "~") for part in parts]

    def replace(current: Any, index: int) -> Any:
        if index == len(parts):
            return replacement
        part = parts[index]
        if isinstance(current, list):
            copied = list(current)
            copied[int(part)] = replace(copied[int(part)], index + 1)
            return copied
        if isinstance(current, dict):
            copied = dict(current)
            if part in copied:
                copied[part] = replace(copied[part], index + 1)
            return copied
        return current

    return replace(value, 0)
