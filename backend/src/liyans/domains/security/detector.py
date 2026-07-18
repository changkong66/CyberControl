from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from liyans_contracts.topic4_c9 import SecurityFindingCategory


@dataclass(frozen=True, slots=True)
class SecurityMatch:
    category: SecurityFindingCategory
    reason_code: str
    severity: str
    path: str
    fingerprint: str
    detector: str
    non_waivable: bool


_PROMPT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "C9_PROMPT_IGNORE_INSTRUCTIONS",
        re.compile(
            r"\b(ignore|disregard|bypass)\b.{0,80}\b(previous|system|developer|policy|instruction)s?\b",
            re.I | re.S,
        ),
    ),
    (
        "C9_PROMPT_SYSTEM_OVERRIDE",
        re.compile(r"\b(system|developer)\s+(prompt|message|instruction)\b", re.I),
    ),
    (
        "C9_PROMPT_SECRET_REQUEST",
        re.compile(
            r"\b(reveal|show|print|leak|exfiltrate)\b.{0,80}\b(secret|token|password|credential|prompt)\b",
            re.I | re.S,
        ),
    ),
    (
        "C9_PROMPT_JAILBREAK",
        re.compile(r"\b(jailbreak|dan\s+mode|developer\s+mode|do\s+anything\s+now)\b", re.I),
    ),
    (
        "C9_PROMPT_TOOL_OVERRIDE",
        re.compile(
            r"\b(call|invoke|execute)\b.{0,60}\b(tool|function|shell|browser)\b.{0,60}\bwithout\b",
            re.I | re.S,
        ),
    ),
)

_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "C9_EXPOSED_PRIVATE_KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    ),
    (
        "C9_EXPOSED_JWT",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "C9_EXPOSED_SERVICE_KEY",
        re.compile(r"\b(?:sk|xox[baprs]|gh[pousr]|AIza)[_-][A-Za-z0-9_-]{12,}\b"),
    ),
    (
        "C9_EXPOSED_DATABASE_SECRET",
        re.compile(r"\b(?:postgres(?:ql)?|mysql|redis)://[^\s:@]+:[^\s@]+@", re.I),
    ),
    (
        "C9_EXPOSED_ASSIGNMENT",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}",
            re.I,
        ),
    ),
)

_MALWARE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "C9_MALWARE_DOWNLOAD_EXECUTE",
        re.compile(
            r"(?:curl|wget|Invoke-WebRequest).{0,160}(?:\||;|&&).{0,80}(?:sh|bash|powershell|pwsh)",
            re.I | re.S,
        ),
    ),
    (
        "C9_MALWARE_ENCODED_COMMAND",
        re.compile(r"\b(?:powershell|pwsh)\b.{0,80}(?:-enc|-encodedcommand)\b", re.I | re.S),
    ),
    (
        "C9_MALWARE_DESTRUCTIVE_SHELL",
        re.compile(r"\b(?:rm\s+-rf|format\s+[a-z]:|diskpart\b|dd\s+if=)", re.I),
    ),
    (
        "C9_MALWARE_RUNTIME_EXEC",
        re.compile(
            r"\b(?:os\.system|subprocess\.(?:run|call|Popen)|child_process\.exec)\s*\(", re.I
        ),
    ),
)

_EXFILTRATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "C9_DATA_EXFILTRATION_UPLOAD",
        re.compile(
            r"\b(?:upload|send|post|forward|exfiltrat)\b.{0,100}\b(?:secret|token|password|credential|private|personal)\b",
            re.I | re.S,
        ),
    ),
    (
        "C9_DATA_EXFILTRATION_WEBHOOK",
        re.compile(r"\b(?:webhook|callback|pastebin|ngrok|requestbin)\b", re.I),
    ),
)

_CONTENT_POLICY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "C9_CONTENT_UNSAFE_INSTRUCTION",
        re.compile(
            r"\b(?:make|build|deploy)\b.{0,80}\b(?:weapon|ransomware|credential\s+stealer|keylogger)\b",
            re.I | re.S,
        ),
    ),
)


class DeterministicSecurityDetector:
    """Scan candidate text without model calls, network access, or raw secret storage."""

    detector_version = "c9-deterministic-detector-v1"

    def __init__(self, *, max_matches: int = 256, max_string_length: int = 32_768) -> None:
        if not 1 <= max_matches <= 4096:
            raise ValueError("max_matches must be between 1 and 4096")
        if not 1 <= max_string_length <= 1_000_000:
            raise ValueError("max_string_length must be between 1 and 1000000")
        self._max_matches = max_matches
        self._max_string_length = max_string_length

    def scan(self, candidate: Any, *, tenant_id: str) -> tuple[SecurityMatch, ...]:
        matches: list[SecurityMatch] = []
        for path, value in self._walk(candidate.model_dump(mode="json")):
            if len(matches) >= self._max_matches:
                break
            if not isinstance(value, str):
                continue
            text = value[: self._max_string_length]
            matches.extend(self._scan_text(text, path, tenant_id))
            matches.extend(self._scan_tenant_reference(text, path, tenant_id))
            if len(matches) >= self._max_matches:
                break
        return tuple(matches[: self._max_matches])

    def _scan_text(self, text: str, path: str, tenant_id: str) -> list[SecurityMatch]:
        del tenant_id
        output: list[SecurityMatch] = []
        for category, patterns, severity, non_waivable, detector in (
            (SecurityFindingCategory.PROMPT_INJECTION, _PROMPT_PATTERNS, "HIGH", False, "prompt"),
            (
                SecurityFindingCategory.EXPOSED_CREDENTIAL,
                _CREDENTIAL_PATTERNS,
                "CRITICAL",
                True,
                "credential",
            ),
            (SecurityFindingCategory.MALWARE, _MALWARE_PATTERNS, "CRITICAL", True, "malware"),
            (
                SecurityFindingCategory.DATA_EXFILTRATION,
                _EXFILTRATION_PATTERNS,
                "CRITICAL",
                True,
                "exfiltration",
            ),
            (
                SecurityFindingCategory.CONTENT_POLICY,
                _CONTENT_POLICY_PATTERNS,
                "HIGH",
                False,
                "content-policy",
            ),
        ):
            for reason_code, pattern in patterns:
                match = pattern.search(text)
                if match is None:
                    continue
                output.append(
                    SecurityMatch(
                        category=category,
                        reason_code=reason_code,
                        severity=severity,
                        path=path,
                        fingerprint=self._fingerprint(text, match.group(0)),
                        detector=f"{self.detector_version}:{detector}",
                        non_waivable=non_waivable,
                    )
                )
        return output

    @staticmethod
    def _scan_tenant_reference(text: str, path: str, tenant_id: str) -> list[SecurityMatch]:
        pattern = re.compile(r"\btenant[_ -]?id\s*[:=]\s*['\"]?([A-Za-z0-9_.:-]{1,128})", re.I)
        for match in pattern.finditer(text):
            if match.group(1) == tenant_id:
                continue
            return [
                SecurityMatch(
                    category=SecurityFindingCategory.CROSS_TENANT_REFERENCE,
                    reason_code="C9_CROSS_TENANT_REFERENCE",
                    severity="CRITICAL",
                    path=path,
                    fingerprint=DeterministicSecurityDetector._fingerprint(text, match.group(1)),
                    detector=f"{DeterministicSecurityDetector.detector_version}:tenant-boundary",
                    non_waivable=True,
                )
            ]
        return []

    @staticmethod
    def _fingerprint(text: str, matched: str) -> str:
        from liyans_contracts.common import canonical_sha256

        return canonical_sha256(
            {"text_sha256": canonical_sha256(text), "match_sha256": canonical_sha256(matched)}
        )

    @classmethod
    def _walk(cls, value: Any, path: str = "") -> list[tuple[str, Any]]:
        if isinstance(value, dict):
            output: list[tuple[str, Any]] = []
            for key, child in value.items():
                child_path = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
                output.extend(cls._walk(child, child_path))
            return output
        if isinstance(value, list):
            output = []
            for index, child in enumerate(value):
                output.extend(cls._walk(child, f"{path}/{index}"))
            return output
        return [(path or "/", value)]
