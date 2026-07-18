from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid5

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_c1 import (
    PublicationBatchV1,
    PublicationState,
    PublicStreamEventV1,
    VerificationReportV1,
)
from liyans_contracts.topic4_common import AggregateDecision
from liyans_contracts.verification import ReleaseAuthorizationPayloadV1

from liyans.core.tenant import TenantContext, assert_tenant, current_tenant
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.infrastructure.persistence.artifacts import ArtifactObjectStore


class ReleaseError(RuntimeError):
    """Base class for fail-closed C12 publication errors."""


class AuthorizationConflictError(ReleaseError):
    pass


class AuthorizationExpiredError(ReleaseError):
    pass


class AuthorizationReplayError(ReleaseError):
    pass


class PublicationIntegrityError(ReleaseError):
    pass


MAX_AUTHORIZATION_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    authorization: ReleaseAuthorizationPayloadV1
    report: VerificationReportV1
    candidate: CandidateV1
    request_document: dict[str, Any]
    request_sha256: str
    subject_ref: str


@dataclass(frozen=True, slots=True)
class PublicationResult:
    batch: PublicationBatchV1
    public_event: PublicStreamEventV1
    public_artifact: ArtifactObjectRefV1


class AtomicReleaseRepository(Protocol):
    async def get_authorization(
        self,
        authorization_id: UUID,
    ) -> ReleaseAuthorizationPayloadV1 | None: ...

    async def issue_authorization(
        self,
        authorization: ReleaseAuthorizationPayloadV1,
        authorization_document: dict[str, Any],
    ) -> ReleaseAuthorizationPayloadV1: ...

    async def consume_and_publish(
        self,
        request: PublicationRequest,
        public_artifact: ArtifactObjectRefV1,
        event_artifact: ArtifactObjectRefV1,
    ) -> PublicationResult: ...


class ReleasePolicy:
    """Pure C12 binding and expiry policy shared by all repository adapters."""

    @staticmethod
    def validate_authorization(
        authorization: ReleaseAuthorizationPayloadV1,
        *,
        context: TenantContext,
        now: datetime,
    ) -> None:
        assert_tenant(authorization.tenant_id)
        if not record_integrity_valid(authorization):
            raise PublicationIntegrityError("C12 authorization record SHA mismatch")
        if authorization.one_time_use is not True:
            raise PublicationIntegrityError("C12 authorization must be one-time use")
        if authorization.expires_at <= authorization.issued_at:
            raise PublicationIntegrityError("C12 authorization expiry window is invalid")
        if (
            authorization.expires_at - authorization.issued_at
        ).total_seconds() > MAX_AUTHORIZATION_TTL_SECONDS:
            raise PublicationIntegrityError("C12 authorization TTL exceeds the server limit")
        if authorization.expires_at <= now:
            raise AuthorizationExpiredError("C12 authorization is already expired")
        if not authorization.allowed_block_ids:
            raise PublicationIntegrityError("C12 authorization must allow at least one block")
        if (
            authorization.release_mode == "FULL_WITH_DISCLOSURE"
            and not authorization.disclosure_codes
        ):
            raise PublicationIntegrityError("C12 disclosure release requires disclosure codes")
        if authorization.release_mode == "FULL" and authorization.disclosure_codes:
            raise PublicationIntegrityError("C12 full release cannot carry disclosure codes")
        if not context.subject_ref:
            raise PublicationIntegrityError("C12 publishing subject is required")

    @staticmethod
    def validate_request(
        request: PublicationRequest, *, context: TenantContext, now: datetime
    ) -> None:
        authorization = request.authorization
        report = request.report
        candidate = request.candidate
        ReleasePolicy.validate_authorization(authorization, context=context, now=now)
        if not record_integrity_valid(report):
            raise PublicationIntegrityError("C12 verification report record SHA mismatch")
        if request.subject_ref != context.subject_ref:
            raise PublicationIntegrityError("C12 request subject does not match trusted context")
        if canonical_sha256(request.request_document) != request.request_sha256:
            raise PublicationIntegrityError("C12 request SHA does not match request document")
        if report.report_artifact.sha256 != report.report_sha256:
            raise PublicationIntegrityError("C12 report artifact SHA mismatch")
        if (
            canonical_sha256(candidate.model_dump(mode="json", exclude={"candidate_sha256"}))
            != candidate.candidate_sha256
        ):
            raise PublicationIntegrityError("C12 Candidate canonical SHA mismatch")
        if (
            authorization.verification_id != report.verification_id
            or authorization.report_id != report.report_id
            or authorization.candidate_id != candidate.candidate_id
            or authorization.candidate_version != candidate.candidate_version
            or authorization.candidate_sha256 != candidate.candidate_sha256
            or authorization.report_sha256 != report.report_sha256
        ):
            raise PublicationIntegrityError(
                "C12 authorization is not bound to report and Candidate"
            )
        if (
            report.verification_id != authorization.verification_id
            or report.candidate_id != candidate.candidate_id
            or report.candidate_version != candidate.candidate_version
            or report.candidate_sha256 != candidate.candidate_sha256
        ):
            raise PublicationIntegrityError("C12 report is not bound to Candidate")
        block_ids = {block.block_id for block in candidate.blocks}
        allowed = set(authorization.allowed_block_ids)
        if len(allowed) != len(authorization.allowed_block_ids) or not allowed <= block_ids:
            raise PublicationIntegrityError("C12 authorization contains an invalid block set")
        if authorization.release_mode == "FULL" and allowed != block_ids:
            raise PublicationIntegrityError("FULL C12 release must include every Candidate block")
        expected_decision = (
            AggregateDecision.RELEASE
            if authorization.release_mode == "FULL"
            else AggregateDecision.RELEASE_WITH_DISCLOSURE
        )
        if report.decision != expected_decision:
            raise PublicationIntegrityError(
                "C12 authorization release mode disagrees with report decision"
            )
        expected_document = {
            "authorization_id": str(authorization.authorization_id),
            "verification_id": str(authorization.verification_id),
            "report_id": str(authorization.report_id),
            "candidate_id": str(authorization.candidate_id),
            "candidate_version": authorization.candidate_version,
            "candidate_sha256": authorization.candidate_sha256,
            "report_sha256": authorization.report_sha256,
            "allowed_block_ids": authorization.allowed_block_ids,
        }
        if request.request_document == expected_document:
            expected_request_sha256 = canonical_sha256(expected_document)
        elif request.request_document.get("publication") == expected_document:
            if set(request.request_document) != {
                "publication",
                "commit_command_id",
                "idempotency_key_sha256",
            }:
                raise PublicationIntegrityError("C12 v2 request extension contains unknown fields")
            extension = {
                key: request.request_document.get(key)
                for key in ("commit_command_id", "idempotency_key_sha256")
            }
            if not all(isinstance(value, str) and value for value in extension.values()):
                raise PublicationIntegrityError("C12 v2 request extension is incomplete")
            expected_request_sha256 = canonical_sha256(request.request_document)
        else:
            raise PublicationIntegrityError("C12 request document binding mismatch")
        if request.request_sha256 != expected_request_sha256:
            raise PublicationIntegrityError("C12 request SHA does not match its binding document")

    @staticmethod
    def public_document(candidate: CandidateV1, allowed_block_ids: list[str]) -> dict[str, Any]:
        allowed = set(allowed_block_ids)
        return {
            "schema_version": "topic4.public-candidate.v1",
            "candidate_id": str(candidate.candidate_id),
            "candidate_version": candidate.candidate_version,
            "candidate_sha256": candidate.candidate_sha256,
            "resource_type": candidate.resource_type.value,
            "blocks": [
                block.model_dump(mode="json")
                for block in candidate.blocks
                if block.block_id in allowed
            ],
        }


class C12ReleaseService:
    """Fail-closed C12 service with content-addressed public artifacts."""

    def __init__(
        self,
        repository: AtomicReleaseRepository,
        artifact_store: ArtifactObjectStore,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store

    async def get_authorization(
        self, authorization_id: UUID
    ) -> ReleaseAuthorizationPayloadV1 | None:
        return await self._repository.get_authorization(authorization_id)

    async def issue_authorization(
        self,
        authorization: ReleaseAuthorizationPayloadV1,
        *,
        authorization_document: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ReleaseAuthorizationPayloadV1:
        context = current_tenant()
        current = now or datetime.now(UTC)
        ReleasePolicy.validate_authorization(authorization, context=context, now=current)
        document = authorization_document or authorization.model_dump(mode="json")
        if canonical_sha256(document) != canonical_sha256(authorization.model_dump(mode="json")):
            raise PublicationIntegrityError("C12 authorization document is not the frozen payload")
        return await self._repository.issue_authorization(authorization, document)

    async def publish(
        self,
        request: PublicationRequest,
        *,
        now: datetime | None = None,
    ) -> PublicationResult:
        context = current_tenant()
        current = now or datetime.now(UTC)
        ReleasePolicy.validate_request(request, context=context, now=current)
        public_document = ReleasePolicy.public_document(
            request.candidate, request.authorization.allowed_block_ids
        )
        public_artifact = await self._put_document(
            request,
            public_document,
            prefix="c12/public",
        )
        event_document = {
            "schema_version": "topic4.publication.event.v1",
            "authorization_id": str(request.authorization.authorization_id),
            "verification_id": str(request.authorization.verification_id),
            "candidate_id": str(request.candidate.candidate_id),
            "candidate_version": request.candidate.candidate_version,
            "candidate_sha256": request.candidate.candidate_sha256,
            "report_sha256": request.report.report_sha256,
            "public_artifact": public_artifact.model_dump(mode="json"),
        }
        event_artifact = await self._put_document(request, event_document, prefix="c12/events")
        return await self._repository.consume_and_publish(request, public_artifact, event_artifact)

    async def _put_document(
        self,
        request: PublicationRequest,
        document: dict[str, Any],
        *,
        prefix: str,
    ) -> ArtifactObjectRefV1:
        content = canonical_json_bytes(document)
        digest = canonical_sha256(document)
        object_key = (
            f"{prefix}/{request.authorization.verification_id}/"
            f"{request.authorization.authorization_id}/{digest}.json"
        )
        stored = await self._artifact_store.put(
            tenant_id=request.authorization.tenant_id,
            storage_namespace="verification-artifacts",
            object_key=object_key,
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise PublicationIntegrityError("C12 artifact store returned invalid metadata")
        return ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=object_key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=request.candidate.created_at,
        )


class InMemoryAtomicReleaseRepository:
    """Deterministic test adapter mirroring C12 one-time atomic semantics."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._authorizations: dict[UUID, tuple[ReleaseAuthorizationPayloadV1, dict[str, Any]]] = {}
        self._consumed: dict[UUID, tuple[str, PublicationResult]] = {}

    async def issue_authorization(self, authorization, authorization_document):
        async with self._lock:
            existing = self._authorizations.get(authorization.authorization_id)
            if existing is not None:
                if canonical_sha256(existing[1]) != canonical_sha256(authorization_document):
                    raise AuthorizationConflictError("C12 authorization identity conflict")
                return existing[0]
            self._authorizations[authorization.authorization_id] = (
                authorization,
                dict(authorization_document),
            )
            return authorization

    async def get_authorization(self, authorization_id: UUID):
        async with self._lock:
            stored = self._authorizations.get(authorization_id)
            return None if stored is None else stored[0]

    async def consume_and_publish(self, request, public_artifact, event_artifact):
        async with self._lock:
            stored = self._authorizations.get(request.authorization.authorization_id)
            if stored is None:
                raise AuthorizationConflictError("C12 authorization has not been issued")
            stored_authorization, stored_document = stored
            if (
                canonical_sha256(stored_document)
                != canonical_sha256(request.authorization.model_dump(mode="json"))
                or stored_authorization != request.authorization
            ):
                raise AuthorizationConflictError(
                    "C12 authorization payload does not match the issued record"
                )
            existing = self._consumed.get(request.authorization.authorization_id)
            if existing is not None:
                if existing[0] != request.request_sha256:
                    raise AuthorizationReplayError("C12 authorization replay request differs")
                return existing[1]
            now = self._clock()
            if request.authorization.expires_at <= now:
                raise AuthorizationExpiredError("C12 authorization expired before consumption")
            batch_id = uuid5(
                request.authorization.authorization_id, f"batch:{request.request_sha256}"
            )
            event_id = uuid5(batch_id, "public-event")
            stream_id = uuid5(batch_id, "public-stream")
            batch = build_topic4_record(
                PublicationBatchV1,
                schema_version="publication-batch.v1",
                trace_id=request.authorization.trace_id,
                tenant_id=request.authorization.tenant_id,
                version_cas=2,
                created_at=request.candidate.created_at,
                immutable=True,
                publication_batch_id=batch_id,
                authorization_id=request.authorization.authorization_id,
                verification_id=request.authorization.verification_id,
                report_id=request.authorization.report_id,
                candidate_id=request.candidate.candidate_id,
                candidate_version=request.candidate.candidate_version,
                candidate_sha256=request.candidate.candidate_sha256,
                state=PublicationState.COMMITTED,
                public_artifacts=[public_artifact],
                outbox_event_ids=[uuid5(batch_id, "outbox")],
                public_stream_event_ids=[event_id],
                committed_at=now,
            )
            payload_sha = event_artifact.sha256
            public_event = build_topic4_record(
                PublicStreamEventV1,
                schema_version="public.stream.event.v1",
                trace_id=request.authorization.trace_id,
                tenant_id=request.authorization.tenant_id,
                version_cas=1,
                created_at=request.candidate.created_at,
                immutable=True,
                public_event_id=event_id,
                publication_batch_id=batch_id,
                authorization_id=request.authorization.authorization_id,
                stream_id=stream_id,
                sequence=0,
                event_type="topic4.publication.committed",
                payload_artifact=event_artifact,
                payload_sha256=payload_sha,
                emitted_at=now,
            )
            result = PublicationResult(batch, public_event, public_artifact)
            self._consumed[request.authorization.authorization_id] = (
                request.request_sha256,
                result,
            )
            return result


def canonical_json_bytes(value: Any) -> bytes:
    import json

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
