from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4, uuid5

import pytest
from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import VerificationTrigger
from liyans_contracts.envelope import Topic3EnvelopeV1
from liyans_contracts.topic3 import BlockV1
from liyans_contracts.topic4_c1 import RevisionRequestV1
from liyans_contracts.topic4_c8 import RevisionOperation, RevisionPatchV1
from liyans_contracts.topic4_common import VerificationModule
from prometheus_client import CollectorRegistry
from sqlalchemy import func, select

from liyans.core.tenant import tenant_scope
from liyans.domains.release.engine import C12ReleaseService
from liyans.domains.release.postgres_repository import PostgresAtomicReleaseRepository
from liyans.domains.verification.execution import BoundedModuleExecutor
from liyans.domains.verification.models import Topic4ClaimModel, Topic4VerificationReportModel
from liyans.domains.verification.records import build_topic4_record
from liyans.domains.verification.release_models import (
    Topic4PublicationBatchModel,
    Topic4PublicStreamEventModel,
    Topic4ReleaseAuthorizationConsumptionModel,
)
from liyans.domains.verification.runtime import (
    TOPIC4_VERIFICATION_TASK,
    Topic3CandidateVerificationConsumer,
    Topic4PublicationSSEConsumer,
    Topic4RuntimeMetrics,
)
from liyans.infrastructure.database.context import current_session_context
from liyans.infrastructure.database.models import OutboxMessageModel
from liyans.infrastructure.messaging import AsyncMessageBus, DispatchStatus
from liyans.infrastructure.messaging.postgres_idempotency import PostgresIdempotencyStore
from liyans.infrastructure.streaming.postgres_replay import PostgresSSEReplayLog
from liyans.infrastructure.streaming.sse import SSEBroker
from liyans.infrastructure.tasks.queue import AsyncTaskQueue

from .test_postgres_topic4 import _NotApplicableHandler
from .test_postgres_topic4_knowledge import COURSE_ID, KP_ID
from .topic4_runtime_support import (
    build_publication_request,
    build_release_authorization,
    build_topic4_runtime_fixture,
    finalize_release_report,
)

pytestmark = pytest.mark.integration


async def _revision_request_and_patch(fixture, verification_id, claim_id):
    now = datetime.now(UTC)
    candidate = fixture.candidate
    source_block = candidate.blocks[0]
    content = dict(source_block.content)
    content["summary"] = ["Corrected pole locations determine closed-loop stability."]
    replacement = BlockV1.model_validate(
        source_block.model_copy(
            update={
                "content": content,
                "content_sha256": canonical_sha256(content),
                "created_at": now,
            }
        ).model_dump(mode="json")
    )
    revision_request_id = uuid4()
    instruction_content = b"replace the stability summary with the evidence-backed correction"
    instruction_object = await fixture.artifact_store.put(
        tenant_id=fixture.context.tenant_id,
        storage_namespace="verification-artifacts",
        object_key=f"topic4/revisions/{revision_request_id}/instructions.txt",
        content=instruction_content,
    )
    replacement_content = json.dumps(
        replacement.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    replacement_object = await fixture.artifact_store.put(
        tenant_id=fixture.context.tenant_id,
        storage_namespace="verification-artifacts",
        object_key=f"topic4/revisions/{revision_request_id}/{source_block.block_id}.json",
        content=replacement_content,
    )

    def artifact_ref(stored, object_key: str, media_type: str) -> ArtifactObjectRefV1:
        return ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=object_key,
            media_type=media_type,
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=now,
        )

    instruction_ref = artifact_ref(
        instruction_object,
        f"topic4/revisions/{revision_request_id}/instructions.txt",
        "text/plain",
    )
    replacement_ref = artifact_ref(
        replacement_object,
        f"topic4/revisions/{revision_request_id}/{source_block.block_id}.json",
        "application/json",
    )
    request = build_topic4_record(
        RevisionRequestV1,
        schema_version="revision.request.v1",
        trace_id=fixture.context.trace_id,
        tenant_id=fixture.context.tenant_id,
        version_cas=1,
        created_at=now,
        immutable=True,
        revision_request_id=revision_request_id,
        verification_id=verification_id,
        parent_verification_id=verification_id,
        original_candidate_id=candidate.candidate_id,
        original_candidate_version=candidate.candidate_version,
        original_candidate_sha256=candidate.candidate_sha256,
        target_agent=candidate.provenance.agent,
        revision_round=candidate.candidate_version,
        block_ids=[source_block.block_id],
        claim_ids=[claim_id],
        instructions_artifact=instruction_ref,
        instructions_sha256=instruction_ref.sha256,
        deadline_at=now + timedelta(hours=1),
    )
    cycle_id = uuid5(revision_request_id, "topic4-c8-cycle")
    patch = build_topic4_record(
        RevisionPatchV1,
        schema_version="revision-patch.v1",
        trace_id=fixture.context.trace_id,
        tenant_id=fixture.context.tenant_id,
        version_cas=1,
        created_at=now,
        immutable=True,
        revision_patch_id=uuid5(revision_request_id, f"patch:{source_block.block_id}"),
        revision_plan_id=uuid5(cycle_id, "topic4-c8-plan"),
        block_id=source_block.block_id,
        operation=RevisionOperation.REPLACE_BLOCK,
        base_block_sha256=source_block.content_sha256,
        replacement_artifact=replacement_ref,
        replacement_sha256=replacement.content_sha256,
        target_content_schema_version=source_block.content_schema_version,
        reason_claim_ids=[claim_id],
    )
    return request, patch


@pytest.mark.asyncio
async def test_topic4_runtime_wires_candidate_to_atomic_release_and_persistent_sse(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="runtime-e2e",
    )
    context = fixture.context
    runtime = fixture.runtime

    with tenant_scope(context):
        request = await runtime._request_for_candidate(
            fixture.candidate,
            context=context,
            source_envelope_id=uuid4(),
            trigger=VerificationTrigger.INITIAL_GENERATION,
            parent_verification_id=None,
            course_id=COURSE_ID,
            target_kp_id=KP_ID,
        )
        accepted = await runtime.accept(request, enqueue=False)
        result = await runtime.execute(request.verification_id)
        snapshot = await runtime.snapshot(request.verification_id)
        trace = await runtime.trace(context.trace_id)

        revision_request, revision_patch = await _revision_request_and_patch(
            fixture,
            request.verification_id,
            UUID(snapshot["claims"][0]["claim_id"]),
        )
        revision = await runtime.revision(revision_request, [revision_patch])
        revised_snapshot = await runtime.execute(revision.reverification.verification_id)

        release_request, finalized = await finalize_release_report(fixture)
        issued_at = datetime.now(UTC)
        authorization = build_release_authorization(
            fixture,
            finalized.report,
            issued_at=issued_at,
        )
        publication_request = build_publication_request(
            fixture,
            authorization,
            finalized.report,
        )
        postgres_release = C12ReleaseService(
            PostgresAtomicReleaseRepository(
                fixture.database,
                fixture.outbox,
                instance_id="topic4-runtime-c12",
                clock=lambda: issued_at,
            ),
            fixture.artifact_store,
        )
        await postgres_release.issue_authorization(authorization, now=issued_at)

        async def publish_once():
            started = perf_counter()
            published = await postgres_release.publish(publication_request, now=issued_at)
            return published, (perf_counter() - started) * 1000

        publications = await asyncio.gather(*(publish_once() for _ in range(200)))
        batch_ids = {item.batch.publication_batch_id for item, _elapsed in publications}
        replay_latencies = []
        for _ in range(25):
            _published, elapsed = await publish_once()
            replay_latencies.append(elapsed)
        history = await runtime.publication_history(
            verification_id=release_request.verification_id,
        )
        first_publication = publications[0][0]
        async with fixture.database.transaction(context=current_session_context()) as session:
            consumption_count = await session.scalar(
                select(func.count())
                .select_from(Topic4ReleaseAuthorizationConsumptionModel)
                .where(
                    Topic4ReleaseAuthorizationConsumptionModel.tenant_id == context.tenant_id,
                    Topic4ReleaseAuthorizationConsumptionModel.authorization_id
                    == authorization.authorization_id,
                )
            )
            batch_count = await session.scalar(
                select(func.count())
                .select_from(Topic4PublicationBatchModel)
                .where(
                    Topic4PublicationBatchModel.tenant_id == context.tenant_id,
                    Topic4PublicationBatchModel.authorization_id == authorization.authorization_id,
                )
            )
            public_event_count = await session.scalar(
                select(func.count())
                .select_from(Topic4PublicStreamEventModel)
                .where(
                    Topic4PublicStreamEventModel.tenant_id == context.tenant_id,
                    Topic4PublicStreamEventModel.authorization_id == authorization.authorization_id,
                )
            )
            outbox_row = (
                await session.execute(
                    select(OutboxMessageModel).where(
                        OutboxMessageModel.tenant_id == context.tenant_id,
                        OutboxMessageModel.outbox_id == first_publication.batch.outbox_event_ids[0],
                    )
                )
            ).scalar_one()

        publication_envelope = Topic3EnvelopeV1.model_validate(outbox_row.envelope_document)
        replay_log = PostgresSSEReplayLog(fixture.database)
        broker = SSEBroker(replay_log)
        metrics = Topic4RuntimeMetrics(CollectorRegistry())
        bus = AsyncMessageBus(
            idempotency_store=PostgresIdempotencyStore(
                fixture.database,
                instance_id="topic4-publication-consumer",
            )
        )
        bus.register(
            "topic4.publication.committed",
            Topic4PublicationSSEConsumer(broker, metrics),
        )
        bus.restore_partition_cursor(
            context.tenant_id,
            publication_envelope.partition_key,
            publication_envelope.sequence,
        )
        first_dispatch = await bus.publish(publication_envelope)
        duplicate_dispatch = await bus.publish(publication_envelope)
        replayed_events = await replay_log.replay(context.tenant_id, None)
        await bus.close()

    assert accepted["accepted"]["verification_id"] == str(request.verification_id)
    assert result["verification"]["verification_id"] == str(request.verification_id)
    assert snapshot["report"] is not None
    assert revision.cycle.state.value == "COMPLETED"
    assert revision.candidate.candidate.candidate_version == 2
    assert revised_snapshot["report"] is not None
    assert snapshot["state"]["current_state"] in {
        "RELEASE_PENDING",
        "REVISION_PLANNING",
        "REVIEW_REQUIRED",
    }
    assert trace["tenant_id"] == context.tenant_id
    assert any(record["table"] == "topic4_verifications" for record in trace["records"])
    assert len(batch_ids) == 1
    assert consumption_count == 1
    assert batch_count == 2
    assert public_event_count == 1
    assert any(record["table"] == "topic4_publication_batches" for record in history)
    assert sorted(replay_latencies)[int(len(replay_latencies) * 0.95) - 1] <= 300
    assert first_dispatch.status == DispatchStatus.PROCESSED
    assert duplicate_dispatch.status == DispatchStatus.DUPLICATE
    assert len(replayed_events) == 1
    assert replayed_events[0].event_type == "topic4.publication.committed"


@pytest.mark.asyncio
async def test_topic3_consumer_and_two_hundred_verifications_are_lossless(
    postgres_runtime,
    tmp_path: Path,
) -> None:
    fixture = await build_topic4_runtime_fixture(
        postgres_runtime,
        tmp_path,
        instance_suffix="runtime-concurrency",
    )
    runtime = fixture.runtime
    runtime.executor = BoundedModuleExecutor(
        {module: _NotApplicableHandler() for module in VerificationModule},
        worker_instance_id="topic4-concurrency-worker",
        retry_backoff_ms=0,
    )
    queue = AsyncTaskQueue(
        worker_count=8,
        queue_capacity=512,
        per_tenant_capacity=512,
        per_tenant_refill_per_second=512,
        task_concurrency=32,
    )
    runtime.task_queue = queue
    queue.register(TOPIC4_VERIFICATION_TASK, runtime.handle_queue_task)
    await queue.start()

    with tenant_scope(fixture.context):
        async with fixture.database.transaction(context=current_session_context()) as session:
            finalized_row = (
                await session.execute(
                    select(OutboxMessageModel)
                    .where(
                        OutboxMessageModel.tenant_id == fixture.context.tenant_id,
                        OutboxMessageModel.event_type == "topic3.workflow.finalized",
                    )
                    .order_by(OutboxMessageModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one()
        finalized_envelope = Topic3EnvelopeV1.model_validate(finalized_row.envelope_document)
        bus = AsyncMessageBus(
            idempotency_store=PostgresIdempotencyStore(
                fixture.database,
                instance_id="topic3-topic4-consumer",
            )
        )
        bus.register(
            "topic3.workflow.finalized",
            Topic3CandidateVerificationConsumer(runtime, fixture.topic3_service),
        )
        bus.restore_partition_cursor(
            fixture.context.tenant_id,
            finalized_envelope.partition_key,
            finalized_envelope.sequence,
        )
        first_dispatch = await bus.publish(finalized_envelope)
        duplicate_dispatch = await bus.publish(finalized_envelope)
        await queue.close()
        await bus.close()

        automatic_verification_id = uuid5(
            fixture.candidate.candidate_id,
            (
                "topic4-verification:"
                f"{fixture.candidate.candidate_version}:{fixture.candidate.candidate_sha256}"
            ),
        )
        automatic_snapshot = await runtime.snapshot(automatic_verification_id)

        requests = [
            await runtime._request_for_candidate(
                fixture.candidate,
                context=fixture.context,
                source_envelope_id=uuid4(),
                trigger=VerificationTrigger.INITIAL_GENERATION,
                parent_verification_id=None,
                verification_id=uuid4(),
                course_id=COURSE_ID,
                target_kp_id=KP_ID,
            )
            for _ in range(200)
        ]
        accepted = await asyncio.gather(
            *(runtime.accept(request, enqueue=False) for request in requests)
        )
        completed = await asyncio.gather(
            *(runtime.execute(request.verification_id) for request in requests)
        )
        verification_ids = [request.verification_id for request in requests]
        async with fixture.database.transaction(context=current_session_context()) as session:
            claim_count = await session.scalar(
                select(func.count())
                .select_from(Topic4ClaimModel)
                .where(
                    Topic4ClaimModel.tenant_id == fixture.context.tenant_id,
                    Topic4ClaimModel.verification_id.in_(verification_ids),
                )
            )
            distinct_claim_count = await session.scalar(
                select(func.count(func.distinct(Topic4ClaimModel.claim_id))).where(
                    Topic4ClaimModel.tenant_id == fixture.context.tenant_id,
                    Topic4ClaimModel.verification_id.in_(verification_ids),
                )
            )
            report_count = await session.scalar(
                select(func.count())
                .select_from(Topic4VerificationReportModel)
                .where(
                    Topic4VerificationReportModel.tenant_id == fixture.context.tenant_id,
                    Topic4VerificationReportModel.verification_id.in_(verification_ids),
                )
            )

    assert first_dispatch.status == DispatchStatus.PROCESSED
    assert duplicate_dispatch.status == DispatchStatus.DUPLICATE
    assert automatic_snapshot["report"] is not None
    assert not queue.dead_letters
    assert len(accepted) == 200
    assert len(completed) == 200
    assert len({item["verification"]["verification_id"] for item in completed}) == 200
    assert claim_count is not None and claim_count >= 200
    assert distinct_claim_count == claim_count
    assert report_count == 200
