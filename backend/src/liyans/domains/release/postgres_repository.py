from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from liyans_contracts.common import canonical_sha256
from liyans_contracts.envelope import (
    DeliveryMetadataV1,
    MessageKind,
    MessagePriority,
    ProducerMetadataV1,
    Topic3EnvelopeV1,
)
from liyans_contracts.topic4_c1 import PublicationBatchV1, PublicationState, PublicStreamEventV1
from liyans_contracts.verification import ReleaseAuthorizationPayloadV1
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.tenant import assert_tenant, current_tenant
from liyans.domains.verification.release_models import (
    Topic4PublicationBatchModel,
    Topic4PublicStreamEventModel,
    Topic4ReleaseAuthorizationConsumptionModel,
    Topic4ReleaseAuthorizationModel,
)
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import AuditEventModel, OutboxMessageModel
from liyans.infrastructure.database.session import (
    DatabaseSessionManager,
    TransactionIsolation,
    TransactionRetryPolicy,
)
from liyans.infrastructure.observability.audit import (
    GENESIS_HASH,
    AuditDraft,
    AuditRecord,
    build_audit_record,
)
from liyans.infrastructure.persistence.outbox import OutboxMessage
from liyans.infrastructure.persistence.postgres_outbox import PostgresOutboxRepository

from ..verification.records import build_topic4_record, record_integrity_valid
from .engine import (
    AtomicReleaseRepository,
    AuthorizationConflictError,
    AuthorizationExpiredError,
    AuthorizationReplayError,
    PublicationIntegrityError,
    PublicationResult,
)


class PostgresAtomicReleaseRepository(AtomicReleaseRepository):
    """C12 PostgreSQL repository; every publish mutation shares one SERIALIZABLE transaction."""

    def __init__(
        self,
        database: DatabaseSessionManager,
        outbox: PostgresOutboxRepository,
        *,
        instance_id: str = "topic4-release",
        build_version: str = "topic4-c12-release-v1",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._outbox = outbox
        self._instance_id = instance_id
        self._build_version = build_version
        self._clock = clock or (lambda: datetime.now(UTC))

    async def issue_authorization(self, authorization, authorization_document):
        context = current_tenant()
        assert_tenant(authorization.tenant_id)
        if not record_integrity_valid(authorization):
            raise PublicationIntegrityError("C12 authorization record SHA mismatch")
        if canonical_sha256(authorization_document) != canonical_sha256(
            authorization.model_dump(mode="json")
        ):
            raise PublicationIntegrityError("C12 authorization document is not the frozen payload")

        async def operation(session: AsyncSession) -> ReleaseAuthorizationPayloadV1:
            await self._lock(
                session, f"c12:authorization:{context.tenant_id}:{authorization.authorization_id}"
            )
            result = await session.execute(
                select(Topic4ReleaseAuthorizationModel).where(
                    Topic4ReleaseAuthorizationModel.tenant_id == context.tenant_id,
                    Topic4ReleaseAuthorizationModel.authorization_id
                    == authorization.authorization_id,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                if canonical_sha256(existing.authorization_document) != canonical_sha256(
                    authorization_document
                ):
                    raise AuthorizationConflictError("C12 authorization identity conflict")
                self._assert_authorization_row_matches(existing, authorization)
                return authorization
            audit = await self._append_audit(
                session,
                context,
                action="release_authorization_issued",
                target_ref=str(authorization.authorization_id),
                metadata={"authorization_sha256": authorization.record_sha256},
            )
            session.add(
                Topic4ReleaseAuthorizationModel(
                    authorization_record_id=uuid5(authorization.authorization_id, "record"),
                    authorization_id=authorization.authorization_id,
                    verification_id=authorization.verification_id,
                    report_id=authorization.report_id,
                    candidate_id=authorization.candidate_id,
                    candidate_version=authorization.candidate_version,
                    candidate_sha256=authorization.candidate_sha256,
                    report_sha256=authorization.report_sha256,
                    release_mode=authorization.release_mode,
                    allowed_block_ids=authorization.allowed_block_ids,
                    issued_at=authorization.issued_at,
                    expires_at=authorization.expires_at,
                    one_time_use=authorization.one_time_use,
                    authorization_document=authorization_document,
                    tenant_id=authorization.tenant_id,
                    trace_id=authorization.trace_id,
                    version_cas=authorization.version_cas,
                    record_sha256=authorization.record_sha256,
                    immutable=True,
                    audit_event_id=audit.event_id,
                    created_at=authorization.created_at,
                )
            )
            await session.flush()
            return authorization

        return await self._database.run_transaction(
            operation,
            context=current_session_context(),
            isolation=TransactionIsolation.SERIALIZABLE,
            retry_policy=TransactionRetryPolicy(max_attempts=3),
        )

    async def consume_and_publish(self, request, public_artifact, event_artifact):
        context = current_tenant()
        assert_tenant(request.authorization.tenant_id)

        async def operation(session: AsyncSession) -> PublicationResult:
            await self._lock(
                session,
                (f"c12:authorization:{context.tenant_id}:{request.authorization.authorization_id}"),
            )
            authorization = await self._authorization(
                session, context, request.authorization.authorization_id
            )
            if authorization is None:
                raise AuthorizationConflictError("C12 authorization has not been issued")
            self._assert_authorization_row_matches(authorization, request.authorization)
            if not record_integrity_valid(request.authorization):
                raise PublicationIntegrityError("C12 authorization record SHA mismatch")
            if not record_integrity_valid(request.report):
                raise PublicationIntegrityError("C12 verification report record SHA mismatch")
            consumed = await self._consumption(
                session, context, request.authorization.authorization_id
            )
            if consumed is not None:
                if consumed.request_sha256 != request.request_sha256:
                    raise AuthorizationReplayError("C12 authorization replay request differs")
                return await self._replay(session, context, consumed.publication_batch_id)
            if authorization.expires_at <= self._clock():
                raise AuthorizationExpiredError("C12 authorization expired before consumption")

            batch_id = uuid5(
                request.authorization.authorization_id, f"batch:{request.request_sha256}"
            )
            event_id = uuid5(batch_id, "public-event")
            stream_id = uuid5(batch_id, "public-stream")
            audit = await self._append_audit(
                session,
                context,
                action="publication_committed",
                target_ref=str(batch_id),
                metadata={
                    "authorization_id": str(request.authorization.authorization_id),
                    "candidate_sha256": request.candidate.candidate_sha256,
                    "report_sha256": request.report.report_sha256,
                },
            )
            pending = build_topic4_record(
                PublicationBatchV1,
                schema_version="publication-batch.v1",
                trace_id=request.authorization.trace_id,
                tenant_id=context.tenant_id,
                version_cas=1,
                created_at=request.candidate.created_at,
                immutable=True,
                publication_batch_id=batch_id,
                authorization_id=request.authorization.authorization_id,
                verification_id=request.authorization.verification_id,
                report_id=request.authorization.report_id,
                candidate_id=request.candidate.candidate_id,
                candidate_version=request.candidate.candidate_version,
                candidate_sha256=request.candidate.candidate_sha256,
                state=PublicationState.PENDING,
            )
            session.add(self._batch_row(pending, audit.event_id, 1))
            consumption_id = uuid5(
                request.authorization.authorization_id, f"consumption:{request.request_sha256}"
            )
            session.add(
                Topic4ReleaseAuthorizationConsumptionModel(
                    consumption_record_id=uuid5(consumption_id, "record"),
                    consumption_id=consumption_id,
                    authorization_id=request.authorization.authorization_id,
                    publication_batch_id=batch_id,
                    request_sha256=request.request_sha256,
                    consumed_by_subject=context.subject_ref,
                    consumed_at=self._clock(),
                    consumption_document={
                        "request_sha256": request.request_sha256,
                        "authorization_id": str(request.authorization.authorization_id),
                    },
                    tenant_id=context.tenant_id,
                    trace_id=request.authorization.trace_id,
                    version_cas=1,
                    record_sha256=canonical_sha256(
                        {
                            "consumption_id": str(consumption_id),
                            "request_sha256": request.request_sha256,
                        }
                    ),
                    immutable=True,
                    audit_event_id=audit.event_id,
                    created_at=request.candidate.created_at,
                )
            )
            outbox_id = uuid5(batch_id, "outbox")
            await self._append_outbox(
                session, context, request, outbox_id, batch_id, event_artifact
            )
            public_event = build_topic4_record(
                PublicStreamEventV1,
                schema_version="public.stream.event.v1",
                trace_id=request.authorization.trace_id,
                tenant_id=context.tenant_id,
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
                payload_sha256=event_artifact.sha256,
                emitted_at=self._clock(),
            )
            committed = build_topic4_record(
                PublicationBatchV1,
                **{
                    **pending.model_dump(mode="python", exclude={"record_sha256"}),
                    "version_cas": 2,
                    "state": PublicationState.COMMITTED,
                    "public_artifacts": [public_artifact],
                    "outbox_event_ids": [outbox_id],
                    "public_stream_event_ids": [event_id],
                    "committed_at": self._clock(),
                },
            )
            session.add(self._batch_row(committed, audit.event_id, 2))
            await session.flush()
            session.add(
                Topic4PublicStreamEventModel(
                    public_event_record_id=uuid5(event_id, "record"),
                    public_event_id=event_id,
                    publication_batch_id=batch_id,
                    publication_batch_version=2,
                    authorization_id=request.authorization.authorization_id,
                    stream_id=stream_id,
                    sequence=0,
                    event_type=public_event.event_type,
                    payload_sha256=public_event.payload_sha256,
                    event_document=public_event.model_dump(mode="json"),
                    tenant_id=context.tenant_id,
                    trace_id=public_event.trace_id,
                    version_cas=1,
                    record_sha256=public_event.record_sha256,
                    immutable=True,
                    audit_event_id=audit.event_id,
                    created_at=public_event.created_at,
                    emitted_at=public_event.emitted_at,
                )
            )
            await session.flush()
            return PublicationResult(committed, public_event, public_artifact)

        return await self._database.run_transaction(
            operation,
            context=current_session_context(),
            isolation=TransactionIsolation.SERIALIZABLE,
            retry_policy=TransactionRetryPolicy(max_attempts=3),
        )

    @staticmethod
    async def _lock(session: AsyncSession, key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": key},
        )

    @staticmethod
    async def _authorization(session, context, authorization_id):
        result = await session.execute(
            select(Topic4ReleaseAuthorizationModel).where(
                Topic4ReleaseAuthorizationModel.tenant_id == context.tenant_id,
                Topic4ReleaseAuthorizationModel.authorization_id == authorization_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _consumption(session, context, authorization_id):
        result = await session.execute(
            select(Topic4ReleaseAuthorizationConsumptionModel).where(
                Topic4ReleaseAuthorizationConsumptionModel.tenant_id == context.tenant_id,
                Topic4ReleaseAuthorizationConsumptionModel.authorization_id == authorization_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _replay(session, context, batch_id):
        result = await session.execute(
            select(Topic4PublicationBatchModel)
            .where(
                Topic4PublicationBatchModel.tenant_id == context.tenant_id,
                Topic4PublicationBatchModel.publication_batch_id == batch_id,
                Topic4PublicationBatchModel.state == PublicationState.COMMITTED.value,
            )
            .order_by(Topic4PublicationBatchModel.batch_version.desc())
            .limit(1)
        )
        batch_row = result.scalar_one_or_none()
        if batch_row is None:
            raise PublicationIntegrityError("C12 replay batch is missing")
        try:
            batch = PublicationBatchV1.model_validate(batch_row.batch_document)
        except ValueError as exc:
            raise PublicationIntegrityError("C12 replay batch contract is invalid") from exc
        if (
            not record_integrity_valid(batch)
            or batch.state != PublicationState.COMMITTED
            or batch.version_cas != batch_row.batch_version
            or batch.record_sha256 != batch_row.record_sha256
            or not batch.public_artifacts
            or batch.publication_batch_id != batch_row.publication_batch_id
        ):
            raise PublicationIntegrityError("C12 replay batch integrity is invalid")
        event_result = await session.execute(
            select(Topic4PublicStreamEventModel).where(
                Topic4PublicStreamEventModel.tenant_id == context.tenant_id,
                Topic4PublicStreamEventModel.publication_batch_id == batch_id,
            )
        )
        event_row = event_result.scalar_one_or_none()
        if event_row is None:
            raise PublicationIntegrityError("C12 replay public event is missing")
        try:
            event = PublicStreamEventV1.model_validate(event_row.event_document)
        except ValueError as exc:
            raise PublicationIntegrityError("C12 replay public event contract is invalid") from exc
        if (
            not record_integrity_valid(event)
            or event.publication_batch_id != batch_id
            or event.public_event_id != event_row.public_event_id
            or event.record_sha256 != event_row.record_sha256
            or event.payload_sha256 != event_row.payload_sha256
            or event.payload_artifact.sha256 != event.payload_sha256
        ):
            raise PublicationIntegrityError("C12 replay public event integrity is invalid")
        return PublicationResult(
            batch,
            event,
            batch.public_artifacts[0],
        )

    @staticmethod
    def _assert_authorization_row_matches(
        row, authorization: ReleaseAuthorizationPayloadV1
    ) -> None:
        if (
            row.tenant_id != authorization.tenant_id
            or row.authorization_id != authorization.authorization_id
            or row.verification_id != authorization.verification_id
            or row.report_id != authorization.report_id
            or row.candidate_id != authorization.candidate_id
            or row.candidate_version != authorization.candidate_version
            or row.candidate_sha256 != authorization.candidate_sha256
            or row.report_sha256 != authorization.report_sha256
            or row.release_mode != authorization.release_mode
            or list(row.allowed_block_ids) != list(authorization.allowed_block_ids)
            or row.issued_at != authorization.issued_at
            or row.expires_at != authorization.expires_at
            or row.one_time_use is not True
            or row.trace_id != authorization.trace_id
            or row.version_cas != authorization.version_cas
            or row.record_sha256 != authorization.record_sha256
            or canonical_sha256(row.authorization_document)
            != canonical_sha256(authorization.model_dump(mode="json"))
        ):
            raise PublicationIntegrityError(
                "C12 authorization row does not match the trusted payload"
            )

    @staticmethod
    def _batch_row(batch: PublicationBatchV1, audit_event_id: UUID, version: int):
        return Topic4PublicationBatchModel(
            publication_batch_snapshot_id=uuid5(batch.publication_batch_id, f"snapshot:{version}"),
            publication_batch_id=batch.publication_batch_id,
            batch_version=version,
            authorization_id=batch.authorization_id,
            verification_id=batch.verification_id,
            report_id=batch.report_id,
            candidate_id=batch.candidate_id,
            candidate_version=batch.candidate_version,
            candidate_sha256=batch.candidate_sha256,
            state=batch.state.value,
            batch_document=batch.model_dump(mode="json"),
            committed_at=batch.committed_at,
            tenant_id=batch.tenant_id,
            trace_id=batch.trace_id,
            version_cas=version,
            record_sha256=batch.record_sha256,
            immutable=True,
            audit_event_id=audit_event_id,
            created_at=batch.created_at,
        )

    async def _append_outbox(self, session, context, request, outbox_id, batch_id, event_artifact):
        partition = f"topic4:public:{context.tenant_id}:{batch_id}"
        await self._lock(session, f"outbox:{partition}")
        sequence_result = await session.execute(
            select(func.coalesce(func.max(OutboxMessageModel.sequence) + 1, 0)).where(
                OutboxMessageModel.tenant_id == context.tenant_id,
                OutboxMessageModel.partition_key == partition,
            )
        )
        sequence = int(sequence_result.scalar_one())
        now = self._clock()
        payload = {
            "schema_version": "topic4.publication.committed.v1",
            "publication_batch_id": str(batch_id),
            "authorization_id": str(request.authorization.authorization_id),
            "event_artifact": event_artifact.model_dump(mode="json"),
        }
        envelope = Topic3EnvelopeV1(
            envelope_id=uuid5(batch_id, "envelope"),
            event_type="topic4.publication.committed",
            message_kind=MessageKind.EVENT,
            tenant_id=context.tenant_id,
            session_id=context.session_id or request.authorization.verification_id,
            subject_ref=context.subject_ref,
            correlation_id=request.authorization.verification_id,
            causation_id=None,
            sequence=sequence,
            partition_key=partition,
            producer=ProducerMetadataV1(
                agent=None,
                service="topic4-release-service",
                instance_id=self._instance_id,
                build_version=self._build_version,
            ),
            delivery=DeliveryMetadataV1(
                idempotency_key=f"topic4:publication:{batch_id}",
                available_at=now,
                expires_at=now + timedelta(days=7),
                priority=MessagePriority.CRITICAL,
            ),
            resource=None,
            trace_id=context.trace_id,
            span_id=None,
            created_at=now,
            error=None,
            payload=payload,
        )
        await self._outbox.append(
            session,
            OutboxMessage(
                outbox_id=outbox_id,
                tenant_id=context.tenant_id,
                envelope=envelope,
                created_at=now,
                available_at=now,
                published_at=None,
                max_attempts=envelope.delivery.max_attempts,
            ),
        )

    async def _append_audit(self, session, context, *, action, target_ref, metadata) -> AuditRecord:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"audit:{context.tenant_id}"},
        )
        result = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.tenant_id == context.tenant_id)
            .order_by(AuditEventModel.sequence.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        draft = AuditDraft(
            tenant_id=context.tenant_id,
            category="TOPIC4",
            action=action,
            outcome="SUCCEEDED",
            actor_ref=context.subject_ref,
            target_ref=target_ref,
            trace_id=context.trace_id,
            envelope_id=None,
            metadata=metadata,
            occurred_at=self._clock(),
        )
        record = build_audit_record(
            draft,
            0 if previous is None else previous.sequence + 1,
            GENESIS_HASH if previous is None else previous.event_hash,
        )
        session.add(
            AuditEventModel(
                event_id=record.event_id,
                tenant_id=record.tenant_id,
                sequence=record.sequence,
                category=record.category,
                action=record.action,
                outcome=record.outcome,
                actor_ref=record.actor_ref,
                target_ref=record.target_ref,
                trace_id=record.trace_id,
                envelope_id=None,
                event_metadata=record.metadata,
                occurred_at=record.occurred_at,
                previous_hash=record.previous_hash,
                event_hash=record.event_hash,
            )
        )
        await session.flush()
        return record
