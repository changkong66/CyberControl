from __future__ import annotations

import re
from dataclasses import dataclass

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic3 import (
    BlockType,
    CandidateV1,
    CodeFileV1,
    CodeSandboxContentV1,
)
from liyans_contracts.topic4_c1 import ClaimV1
from liyans_contracts.topic4_c6 import CodeLanguage

_BLOCK_POINTER = re.compile(r"^/blocks/(?P<block>\d+)/content(?:/|$)")
_LANGUAGE_MAP = {
    "python": CodeLanguage.PYTHON,
    "matlab": CodeLanguage.MATLAB,
}


class CodeParseError(ValueError):
    """Raised when a Code Claim cannot be bound to a frozen Topic3 code block."""


@dataclass(frozen=True, slots=True)
class ParsedCodeBundle:
    content: CodeSandboxContentV1
    files: tuple[CodeFileV1, ...]
    entrypoint: CodeFileV1
    language: CodeLanguage
    block_ordinal: int
    source_document: dict[str, object]
    source_sha256: str


class FrozenCodeBundleParser:
    def parse(self, claim: ClaimV1, candidate: CandidateV1) -> ParsedCodeBundle:
        if candidate.candidate_id != claim.candidate_id:
            raise CodeParseError("code Candidate identity does not match the Claim")
        if candidate.candidate_version != claim.candidate_version:
            raise CodeParseError("code Candidate version does not match the Claim")
        if candidate.candidate_sha256 != claim.candidate_sha256:
            raise CodeParseError("code Candidate SHA does not match the Claim")
        pointer = _BLOCK_POINTER.match(claim.json_pointer)
        if pointer is None:
            raise CodeParseError("code Claim pointer is not block-scoped")
        block_ordinal = int(pointer.group("block"))
        block = next((item for item in candidate.blocks if item.ordinal == block_ordinal), None)
        if block is None or block.block_id != claim.block_id or block.block_type != BlockType.CODE:
            raise CodeParseError("code Claim block binding is invalid")
        if canonical_sha256(block.content) != block.content_sha256:
            raise CodeParseError("code block content integrity check failed")
        try:
            content = CodeSandboxContentV1.model_validate(block.content)
        except ValueError as exc:
            raise CodeParseError("code block violates the frozen Topic3 contract") from exc
        languages = {_LANGUAGE_MAP[file.language] for file in content.files}
        if len(languages) != 1:
            raise CodeParseError("mixed-language code blocks are not supported by CodeArtifactV1")
        entrypoint = next(file for file in content.files if file.entrypoint)
        source_document: dict[str, object] = {
            "schema_version": "c6-source-bundle.v1",
            "candidate_id": str(candidate.candidate_id),
            "candidate_version": candidate.candidate_version,
            "candidate_sha256": candidate.candidate_sha256,
            "block_id": block.block_id,
            "block_content_sha256": block.content_sha256,
            "title": content.title,
            "objective": content.objective,
            "files": [file.model_dump(mode="json") for file in content.files],
            "parameters": dict(sorted(content.parameters.items())),
            "expected_observations": list(content.expected_observations),
            "result_analysis": content.result_analysis,
            "safety_notes": list(content.safety_notes),
        }
        return ParsedCodeBundle(
            content=content,
            files=tuple(content.files),
            entrypoint=entrypoint,
            language=next(iter(languages)),
            block_ordinal=block_ordinal,
            source_document=source_document,
            source_sha256=canonical_sha256(source_document),
        )
