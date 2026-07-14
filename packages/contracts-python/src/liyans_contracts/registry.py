from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from .artifacts import ArtifactObjectRefV1, SourceSnapshotRefV1
from .envelope import ErrorReceiptV1, Topic3EnvelopeV1
from .providers import ResponsesLiteRequestV1
from .topic3 import BlockV1, CandidateV1, SSEChunkV1
from .verification import (
    ReleaseAuthorizationPayloadV1,
    VerificationAcceptedPayloadV1,
    VerificationBindingV1,
    VerificationRequestPayloadV1,
    VerificationStateChangedPayloadV1,
)


@dataclass(frozen=True, slots=True)
class ContractRegistration:
    schema_name: str
    owner: str
    visibility: str
    compatibility: str
    model: type[BaseModel]


CONTRACT_REGISTRY: tuple[ContractRegistration, ...] = (
    ContractRegistration(
        "artifact.object.ref.v1",
        "verification-platform",
        "internal",
        "strict-v1",
        ArtifactObjectRefV1,
    ),
    ContractRegistration(
        "source.snapshot.ref.v1",
        "verification-platform",
        "internal",
        "strict-v1",
        SourceSnapshotRefV1,
    ),
    ContractRegistration(
        "topic3.envelope.v1",
        "generation-platform",
        "shared",
        "strict-v1",
        Topic3EnvelopeV1,
    ),
    ContractRegistration(
        "topic3.error-receipt.v1",
        "generation-platform",
        "shared",
        "strict-v1",
        ErrorReceiptV1,
    ),
    ContractRegistration(
        "topic3.block.v1",
        "generation-platform",
        "shared",
        "strict-v1",
        BlockV1,
    ),
    ContractRegistration(
        "topic3.candidate.v1",
        "generation-platform",
        "shared",
        "strict-v1",
        CandidateV1,
    ),
    ContractRegistration(
        "topic3.sse-chunk.v1",
        "generation-platform",
        "shared",
        "strict-v1",
        SSEChunkV1,
    ),
    ContractRegistration(
        "responses.lite.request.v1",
        "provider-platform",
        "internal",
        "strict-v1",
        ResponsesLiteRequestV1,
    ),
    ContractRegistration(
        "verification.binding.v1",
        "verification-platform",
        "internal",
        "strict-v1",
        VerificationBindingV1,
    ),
    ContractRegistration(
        "verification.request.v1",
        "verification-platform",
        "internal",
        "strict-v1",
        VerificationRequestPayloadV1,
    ),
    ContractRegistration(
        "verification.accepted.v1",
        "verification-platform",
        "shared",
        "strict-v1",
        VerificationAcceptedPayloadV1,
    ),
    ContractRegistration(
        "verification.state_changed.v1",
        "verification-platform",
        "shared",
        "strict-v1",
        VerificationStateChangedPayloadV1,
    ),
    ContractRegistration(
        "release.authorization.v1",
        "verification-platform",
        "internal",
        "strict-v1",
        ReleaseAuthorizationPayloadV1,
    ),
)
