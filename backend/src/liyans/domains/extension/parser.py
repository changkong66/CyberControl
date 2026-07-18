from __future__ import annotations

import re
from dataclasses import dataclass

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic3 import BlockType, CandidateV1, ExtensionContentV1, ExtensionResourceV1
from liyans_contracts.topic4_c1 import ClaimV1

_RESOURCE_POINTER = re.compile(
    r"^/blocks/(?P<block>\d+)/content/resources/(?P<resource>\d+)(?:/|$)"
)


class ExtensionParseError(ValueError):
    """Raised when a frozen Topic3 extension Claim cannot be reconstructed safely."""


@dataclass(frozen=True, slots=True)
class ParsedExtensionResource:
    resource: ExtensionResourceV1
    content: ExtensionContentV1
    candidate_block_ordinal: int
    resource_ordinal: int


class FrozenExtensionParser:
    def parse(self, claim: ClaimV1, candidate: CandidateV1) -> ParsedExtensionResource:
        if candidate.candidate_id != claim.candidate_id:
            raise ExtensionParseError("extension candidate identity does not match the Claim")
        if candidate.candidate_version != claim.candidate_version:
            raise ExtensionParseError("extension candidate version does not match the Claim")
        if candidate.candidate_sha256 != claim.candidate_sha256:
            raise ExtensionParseError("extension candidate SHA does not match the Claim")

        pointer = _RESOURCE_POINTER.match(claim.json_pointer)
        if pointer is None:
            raise ExtensionParseError("extension Claim pointer is not resource-scoped")
        block_ordinal = int(pointer.group("block"))
        resource_ordinal = int(pointer.group("resource"))
        block = next((item for item in candidate.blocks if item.ordinal == block_ordinal), None)
        if (
            block is None
            or block.block_id != claim.block_id
            or block.block_type != BlockType.EXTENSION
        ):
            raise ExtensionParseError("extension Claim block binding is invalid")
        if canonical_sha256(block.content) != block.content_sha256:
            raise ExtensionParseError("extension block content integrity check failed")
        try:
            content = ExtensionContentV1.model_validate(block.content)
            resource = content.resources[resource_ordinal]
        except (IndexError, ValueError) as exc:
            raise ExtensionParseError(
                "extension block does not satisfy the frozen Extension contract"
            ) from exc
        return ParsedExtensionResource(resource, content, block_ordinal, resource_ordinal)
