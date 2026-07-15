from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from .artifacts import ArtifactObjectRefV1, SourceSnapshotRefV1
from .envelope import ErrorReceiptV1, Topic3EnvelopeV1
from .providers import ResponsesLiteRequestV1
from .topic1 import (
    Topic1ApiEnvelopeV1,
    Topic1CourseV1,
    Topic1GoldenQuestionV1,
    Topic1GraphSnapshotV1,
    Topic1ImportBundleV1,
    Topic1KnowledgePointV1,
    Topic1MisconceptionV1,
    Topic1PrerequisiteV1,
    Topic1TextbookMappingV1,
    Topic1TextbookSectionV1,
    Topic1TextbookV1,
)
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
        "topic1.api-envelope.v1", "topic1", "shared", "strict-v1", Topic1ApiEnvelopeV1
    ),
    ContractRegistration("topic1.course.v1", "topic1", "shared", "strict-v1", Topic1CourseV1),
    ContractRegistration(
        "topic1.knowledge-point.v1",
        "topic1",
        "shared",
        "strict-v1",
        Topic1KnowledgePointV1,
    ),
    ContractRegistration(
        "topic1.prerequisite.v1", "topic1", "shared", "strict-v1", Topic1PrerequisiteV1
    ),
    ContractRegistration(
        "topic1.misconception.v1", "topic1", "shared", "strict-v1", Topic1MisconceptionV1
    ),
    ContractRegistration("topic1.textbook.v1", "topic1", "shared", "strict-v1", Topic1TextbookV1),
    ContractRegistration(
        "topic1.textbook-section.v1",
        "topic1",
        "shared",
        "strict-v1",
        Topic1TextbookSectionV1,
    ),
    ContractRegistration(
        "topic1.textbook-mapping.v1",
        "topic1",
        "shared",
        "strict-v1",
        Topic1TextbookMappingV1,
    ),
    ContractRegistration(
        "topic1.golden-question.v1",
        "topic1",
        "shared",
        "strict-v1",
        Topic1GoldenQuestionV1,
    ),
    ContractRegistration(
        "topic1.import-bundle.v1", "topic1", "internal", "strict-v1", Topic1ImportBundleV1
    ),
    ContractRegistration(
        "topic1.graph-snapshot.v1",
        "topic1",
        "shared",
        "strict-v1",
        Topic1GraphSnapshotV1,
    ),
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
