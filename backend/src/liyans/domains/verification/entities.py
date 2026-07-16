from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from liyans_contracts.verification import (
    VerificationAcceptedPayloadV1,
    VerificationRequestPayloadV1,
    VerificationStateChangedPayloadV1,
)


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    verification_record_id: UUID
    request: VerificationRequestPayloadV1
    accepted: VerificationAcceptedPayloadV1

    def __post_init__(self) -> None:
        if self.request.verification_id != self.accepted.verification_id:
            raise ValueError("request and accepted verification ids differ")
        if self.request.tenant_id != self.accepted.tenant_id:
            raise ValueError("request and accepted tenant ids differ")
        source = self.request.source_snapshot_ref
        if source.candidate_id != self.accepted.source_candidate_id:
            raise ValueError("accepted candidate id differs from source snapshot")
        if source.candidate_version != self.accepted.source_candidate_version:
            raise ValueError("accepted candidate version differs from source snapshot")
        if source.candidate_sha256 != self.accepted.source_candidate_sha256:
            raise ValueError("accepted candidate hash differs from source snapshot")


@dataclass(frozen=True, slots=True)
class VerificationStateRecord:
    state_snapshot_id: UUID
    change: VerificationStateChangedPayloadV1
