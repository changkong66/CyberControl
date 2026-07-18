from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import (
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateProvenanceV1,
    CandidateStatus,
    CandidateV1,
    LecturerContentV1,
)
from liyans_contracts.topic4_c1 import RevisionRequestV1
from liyans_contracts.topic4_c8 import RevisionOperation, RevisionPatchV1

from liyans.core.errors import LiyanError, TenantIsolationError
from liyans.core.tenant import TenantContext, tenant_scope
from liyans.domains.revision.engine import (
    RevisionConflictError,
    RevisionEngine,
    RevisionIntegrityError,
    RevisionLimitError,
)
from liyans.domains.revision.postgres_repository import PostgresRevisionRepository
from liyans.domains.topic3.entities import CandidateRecord
from liyans.domains.verification.records import build_topic4_record
from liyans.infrastructure.persistence.artifacts import StoredArtifactObject

NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
TENANT = "tenant-c8"
TRACE_ID = "0123456789abcdef0123456789abcdef"
VERIFICATION_ID = UUID("f7b148a8-3175-493c-862a-ec104edc84ec")
BLUEPRINT_ID = UUID("c7ad3b38-b4cb-44d2-9c01-2efc1ee826bc")
AUDIT_ID = UUID("f2cc71ca-2d21-4b74-8f22-b24d413d72cb")


class FakeSession:
    def in_transaction(self) -> bool:
        return True


class RecordingSession(FakeSession):
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.statements: list[object] = []
        self.models: list[object] = []
        self.flush_count = 0

    def in_transaction(self) -> bool:
        return self.active

    async def execute(self, statement, _parameters=None):
        self.statements.append(statement)
        return type("Result", (), {"scalar_one_or_none": lambda _self: None})()

    def add(self, model: object) -> None:
        self.models.append(model)

    async def flush(self) -> None:
        self.flush_count += 1


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str, str], bytes] = {}

    async def put(
        self,
        *,
        tenant_id: str,
        storage_namespace: str,
        object_key: str,
        content: bytes,
    ) -> StoredArtifactObject:
        digest = sha256(content).hexdigest()
        key = (tenant_id, storage_namespace, object_key)
        previous = self.objects.get(key)
        if previous is not None and previous != content:
            raise ValueError("immutable artifact conflict")
        self.objects[key] = content
        return StoredArtifactObject(
            tenant_id=tenant_id,
            storage_namespace=storage_namespace,
            object_key=object_key,
            byte_size=len(content),
            sha256=digest,
            created=previous is None,
        )

    async def read(
        self,
        *,
        tenant_id: str,
        storage_namespace: str,
        object_key: str,
        expected_byte_size: int,
        expected_sha256: str,
    ) -> bytes:
        content = self.objects[(tenant_id, storage_namespace, object_key)]
        if len(content) != expected_byte_size or sha256(content).hexdigest() != expected_sha256:
            raise ValueError("artifact integrity failure")
        return content


class FakeTopic3Repository:
    def __init__(self) -> None:
        self.candidates: list[CandidateRecord] = []

    async def append_candidate(
        self,
        _session: FakeSession,
        _tenant_id: str,
        record: CandidateRecord,
        _audit_event_id: UUID,
    ) -> None:
        self.candidates.append(record)


class FakeRevisionRepository:
    def __init__(self) -> None:
        self.cycles: list[tuple[Any, dict[str, Any] | None]] = []
        self.plans: list[Any] = []
        self.patches: list[Any] = []
        self._locks: dict[UUID, asyncio.Lock] = {}
        self.completed: dict[UUID, dict[str, Any]] = {}

    @asynccontextmanager
    async def candidate_lock(self, _session, _tenant_id: str, candidate_id: UUID):
        lock = self._locks.setdefault(candidate_id, asyncio.Lock())
        async with lock:
            yield

    async def find_completed_request(self, _session, _tenant_id: str, request_id: UUID):
        return self.completed.get(request_id)

    async def append_cycle(self, _session, _tenant_id: str, cycle, _audit_event_id, document=None):
        self.cycles.append((cycle, document))
        if cycle.state.value == "COMPLETED":
            self.completed[UUID(document["revision_request_id"])] = {
                "cycle": cycle.model_dump(mode="json"),
                **document,
            }

    async def append_plan(self, _session, _tenant_id: str, plan, _cycle_version, _audit_event_id):
        self.plans.append(plan)

    async def append_patch(self, _session, _tenant_id: str, patch, _audit_event_id):
        self.patches.append(patch)


def _block(
    block_id: str,
    *,
    text: str,
    status: BlockStatus = BlockStatus.COMPLETE,
    ordinal: int = 0,
) -> BlockV1:
    content = LecturerContentV1(
        schema_version="topic3.lecturer-content.v1",
        title="Closed-loop stability",
        learning_objectives=["Explain the stability criterion."],
        sections=[
            {
                "section_id": "section-1",
                "title": "Explanation",
                "depth": "ENGINEERING",
                "markdown": text,
                "target_kp_ids": ["KP_ATC_C"],
            }
        ],
        summary=[text],
    ).model_dump(mode="json")
    return BlockV1(
        schema_version="topic3.block.v1",
        block_id=block_id,
        block_type=BlockType.MARKDOWN,
        ordinal=ordinal,
        title="Stability",
        content_schema_version="topic3.lecturer-content.v1",
        content=content,
        content_sha256=canonical_sha256(content),
        dependency_block_ids=[],
        status=status,
        created_at=NOW,
    )


def _candidate(*, version: int = 1, blocks: list[BlockV1] | None = None) -> CandidateV1:
    blocks = blocks or [_block("block-1", text="Use the Routh-Hurwitz criterion.")]
    draft = CandidateV1.model_construct(
        schema_version="topic3.candidate.v1",
        candidate_id=UUID("e43d9a1e-7d04-4bd0-b6b4-8f4bc6b7a5bd"),
        candidate_version=version,
        parent_candidate_version=None if version == 1 else version - 1,
        blueprint_id=BLUEPRINT_ID,
        blueprint_version="topic3-blueprint.v1",
        blueprint_sha256="a" * 64,
        resource_type=ResourceType.LECTURER_DOC,
        status=CandidateStatus.COMPLETE,
        blocks=blocks,
        provenance=CandidateProvenanceV1(
            agent=SourceAgent.LECTURER,
            agent_build_version="lecturer-build.v1",
            prompt_bundle_version="prompt-bundle.v1",
            provider_alias="local",
            provider_request_ids=[],
        ),
        personalization_policy_digest="b" * 64,
        candidate_sha256="0" * 64,
        created_at=NOW,
    )
    digest = canonical_sha256(draft.model_dump(mode="json", exclude={"candidate_sha256"}))
    return CandidateV1.model_validate(
        draft.model_copy(update={"candidate_sha256": digest}).model_dump(mode="json")
    )


async def _request_and_patch(
    store: MemoryArtifactStore,
    candidate: CandidateV1,
    *,
    operation: RevisionOperation = RevisionOperation.REPLACE_BLOCK,
    replacement: BlockV1 | None = None,
    round: int = 1,
) -> tuple[RevisionRequestV1, tuple[RevisionPatchV1, ...]]:
    request_id = uuid4()
    instructions = b"replace the incorrect stability explanation"
    instruction_object = await store.put(
        tenant_id=TENANT,
        storage_namespace="verification-artifacts",
        object_key=f"c8/instructions/{request_id}.txt",
        content=instructions,
    )
    request = RevisionRequestV1(
        schema_version="revision.request.v1",
        trace_id=TRACE_ID,
        tenant_id=TENANT,
        version_cas=1,
        record_sha256="0" * 64,
        created_at=NOW,
        immutable=True,
        revision_request_id=request_id,
        verification_id=VERIFICATION_ID,
        parent_verification_id=UUID("3a5d8f7d-bb2f-47f4-8d0e-95efaa317ad3"),
        original_candidate_id=candidate.candidate_id,
        original_candidate_version=candidate.candidate_version,
        original_candidate_sha256=candidate.candidate_sha256,
        target_agent=SourceAgent.LECTURER,
        revision_round=round,
        block_ids=["block-1"],
        claim_ids=[UUID("0ed1ef76-83c8-4e2c-8f1e-7ea4bbd2efc6")],
        instructions_artifact=ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=instruction_object.object_key,
            media_type="text/plain",
            content_encoding="identity",
            byte_size=instruction_object.byte_size,
            sha256=instruction_object.sha256,
            created_at=NOW,
        ),
        instructions_sha256=instruction_object.sha256,
        deadline_at=NOW + timedelta(hours=1),
    )
    cycle_id = uuid5(request.revision_request_id, "topic4-c8-cycle")
    plan_id = uuid5(cycle_id, "topic4-c8-plan")
    if operation == RevisionOperation.REPLACE_BLOCK:
        assert replacement is not None
        payload = json_bytes(replacement.model_dump(mode="json"))
        replacement_object = await store.put(
            tenant_id=TENANT,
            storage_namespace="verification-artifacts",
            object_key=f"c8/replacements/{request_id}.json",
            content=payload,
        )
        replacement_artifact = ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=replacement_object.object_key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=replacement_object.byte_size,
            sha256=replacement_object.sha256,
            created_at=NOW,
        )
        replacement_sha256 = replacement.content_sha256
    else:
        replacement_artifact = None
        replacement_sha256 = None
    patch = build_topic4_record(
        RevisionPatchV1,
        trace_id=TRACE_ID,
        tenant_id=TENANT,
        version_cas=1,
        created_at=NOW,
        immutable=True,
        schema_version="revision-patch.v1",
        revision_patch_id=uuid5(request_id, "patch:block-1"),
        revision_plan_id=plan_id,
        block_id="block-1",
        operation=operation,
        base_block_sha256=candidate.blocks[0].content_sha256,
        replacement_artifact=replacement_artifact,
        replacement_sha256=replacement_sha256,
        target_content_schema_version="topic3.lecturer-content.v1",
        reason_claim_ids=list(request.claim_ids),
    )
    return request, (patch,)


def json_bytes(value: object) -> bytes:
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _engine(
    store: MemoryArtifactStore,
    repository: FakeRevisionRepository,
    topic3,
) -> RevisionEngine:
    return RevisionEngine(repository, topic3, store)


def _scope():
    return tenant_scope(
        TenantContext(
            tenant_id=TENANT,
            subject_ref="subject:tester",
            roles=frozenset({"tester"}),
            scopes=frozenset({"topic4:revision"}),
            trace_id=TRACE_ID,
        )
    )


@pytest.mark.asyncio
async def test_c8_replaces_block_and_emits_child_reverification() -> None:
    store = MemoryArtifactStore()
    repository = FakeRevisionRepository()
    topic3 = FakeTopic3Repository()
    base = _candidate()
    replacement = _block("block-1", text="Use the corrected Routh-Hurwitz criterion.")
    request, patches = await _request_and_patch(store, base, replacement=replacement)

    with _scope():
        result = await _engine(store, repository, topic3).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )

    assert result.candidate.candidate.candidate_version == 2
    assert result.candidate.candidate.parent_candidate_version == 1
    assert result.candidate.candidate.blocks[0].content == replacement.content
    assert result.response.revised_candidate_sha256 == result.candidate.candidate.candidate_sha256
    assert result.reverification.trigger.value == "REVISION_REVERIFY"
    assert [cycle.state.value for cycle, _ in repository.cycles] == [
        "LOCKED",
        "GENERATING",
        "COMPLETED",
    ]
    assert len(topic3.candidates) == 1


@pytest.mark.asyncio
async def test_c8_replay_is_idempotent_and_does_not_create_second_candidate() -> None:
    store = MemoryArtifactStore()
    repository = FakeRevisionRepository()
    topic3 = FakeTopic3Repository()
    base = _candidate()
    request, patches = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="A deterministic correction."),
    )
    engine = _engine(store, repository, topic3)

    with _scope():
        first = await engine.revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )
        second = await engine.revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8-retry",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )

    assert first.response == second.response
    assert len(topic3.candidates) == 1
    assert len(repository.cycles) == 3


@pytest.mark.asyncio
async def test_c8_serializes_concurrent_duplicate_requests() -> None:
    store = MemoryArtifactStore()
    repository = FakeRevisionRepository()
    topic3 = FakeTopic3Repository()
    base = _candidate()
    request, patches = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="A concurrency-safe correction."),
    )
    engine = _engine(store, repository, topic3)

    async def run():
        with _scope():
            return await engine.revise(
                FakeSession(),
                tenant_id=TENANT,
                request=request,
                candidate=base,
                patches=patches,
                audit_event_id=AUDIT_ID,
                lock_owner="worker-c8",
                prompt_bundle_version="revision-prompt.v1",
                now=NOW,
            )

    first, second = await asyncio.gather(run(), run())
    assert first.response == second.response
    assert len(topic3.candidates) == 1


@pytest.mark.asyncio
async def test_c8_rejects_stale_block_sha_and_schema_tampering() -> None:
    store = MemoryArtifactStore()
    repository = FakeRevisionRepository()
    topic3 = FakeTopic3Repository()
    base = _candidate()
    request, patches = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="Invalid stale correction."),
    )
    stale = patches[0].model_copy(update={"base_block_sha256": "c" * 64})

    with _scope(), pytest.raises(RevisionConflictError):
        await _engine(store, repository, topic3).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=(stale,),
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )

    object_key = patches[0].replacement_artifact.object_key
    tampered = bytearray(store.objects[(TENANT, "verification-artifacts", object_key)])
    tampered[-2] = ord("x")
    store.objects[(TENANT, "verification-artifacts", object_key)] = bytes(tampered)
    with _scope(), pytest.raises(ValueError):
        await _engine(store, repository, topic3).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_c8_allows_only_terminal_block_removal_without_dangling_dependency() -> None:
    store = MemoryArtifactStore()
    repository = FakeRevisionRepository()
    topic3 = FakeTopic3Repository()
    failed = _block("block-1", text="Failed output.", status=BlockStatus.FAILED)
    retained = _block("block-2", text="Retained output.", ordinal=1)
    base = _candidate(blocks=[failed, retained])
    request, patches = await _request_and_patch(
        store,
        base,
        operation=RevisionOperation.REMOVE_BLOCK,
    )

    with _scope():
        result = await _engine(store, repository, topic3).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )
    assert [block.block_id for block in result.candidate.candidate.blocks] == ["block-2"]
    assert result.candidate.candidate.blocks[0].ordinal == 0

    dependent = _block("block-2", text="Dependent output.", ordinal=1).model_copy(
        update={"dependency_block_ids": ["block-1"]}
    )
    dependent = BlockV1.model_validate(
        {**dependent.model_dump(mode="json"), "content_sha256": dependent.content_sha256}
    )
    dependent_base = _candidate(blocks=[failed, dependent])
    request2, patches2 = await _request_and_patch(
        store,
        dependent_base,
        operation=RevisionOperation.REMOVE_BLOCK,
    )
    with _scope(), pytest.raises(RevisionIntegrityError):
        await _engine(store, FakeRevisionRepository(), FakeTopic3Repository()).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request2,
            candidate=dependent_base,
            patches=patches2,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_c8_enforces_round_limit_and_trusted_tenant() -> None:
    store = MemoryArtifactStore()
    base = _candidate(version=3)
    request, patches = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="Round two."),
        round=2,
    )
    request = request.model_copy(update={"revision_round": 3})
    with _scope(), pytest.raises(RevisionLimitError):
        await _engine(store, FakeRevisionRepository(), FakeTopic3Repository()).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )

    request2, patches2 = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="Wrong tenant."),
    )
    with _scope(), pytest.raises(TenantIsolationError):
        await _engine(store, FakeRevisionRepository(), FakeTopic3Repository()).revise(
            FakeSession(),
            tenant_id="other-tenant",
            request=request2,
            candidate=base,
            patches=patches2,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )


def test_c8_candidate_fixture_is_integrity_valid() -> None:
    candidate = _candidate()
    assert candidate.candidate_sha256 == canonical_sha256(
        candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    )


@pytest.mark.asyncio
async def test_c8_rejects_instruction_artifact_hash_mismatch() -> None:
    store = MemoryArtifactStore()
    base = _candidate()
    request, patches = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="Correction."),
    )
    request = request.model_copy(update={"instructions_sha256": "d" * 64})

    with _scope(), pytest.raises(RevisionIntegrityError):
        await _engine(store, FakeRevisionRepository(), FakeTopic3Repository()).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_postgres_revision_repository_builds_append_only_rows_and_lock() -> None:
    store = MemoryArtifactStore()
    fake_repository = FakeRevisionRepository()
    topic3 = FakeTopic3Repository()
    base = _candidate()
    request, patches = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="Persisted correction."),
    )
    with _scope():
        outcome = await _engine(store, fake_repository, topic3).revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )

        repository = PostgresRevisionRepository()
        session = RecordingSession()
        async with repository.candidate_lock(session, TENANT, base.candidate_id):
            pass
        assert (
            await repository.find_completed_request(
                session,
                TENANT,
                request.revision_request_id,
            )
            is None
        )
        await repository.append_cycle(
            session,
            TENANT,
            outcome.cycle,
            AUDIT_ID,
            document={"revision_request_id": str(request.revision_request_id)},
        )
        await repository.append_plan(
            session,
            TENANT,
            outcome.plan,
            1,
            AUDIT_ID,
        )
        await repository.append_patch(
            session,
            TENANT,
            outcome.patches[0],
            AUDIT_ID,
        )

        with pytest.raises(LiyanError):
            await repository.append_cycle(
                RecordingSession(active=False),
                TENANT,
                outcome.cycle,
                AUDIT_ID,
            )

    assert len(session.statements) == 2
    assert session.flush_count == 3
    assert [model.__tablename__ for model in session.models] == [
        "topic4_revision_cycles",
        "topic4_revision_plans",
        "topic4_revision_patches",
    ]


@pytest.mark.asyncio
async def test_c8_rejects_invalid_runtime_inputs_before_persistence() -> None:
    store = MemoryArtifactStore()
    base = _candidate()
    request, patches = await _request_and_patch(
        store,
        base,
        replacement=_block("block-1", text="Input validation."),
    )

    with _scope(), pytest.raises(ValueError):
        RevisionEngine(
            FakeRevisionRepository(),
            FakeTopic3Repository(),
            store,
            lock_ttl=timedelta(seconds=0),
        )

    engine = _engine(store, FakeRevisionRepository(), FakeTopic3Repository())
    with _scope(), pytest.raises(ValueError):
        await engine.revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )
    with _scope(), pytest.raises(ValueError):
        await engine.revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="",
            now=NOW,
        )
    with _scope(), pytest.raises(ValueError):
        await engine.revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=patches,
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=datetime(2026, 7, 16, 8, 0),
        )
    with _scope(), pytest.raises(RevisionIntegrityError):
        await engine.revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=(),
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )

    wrong_plan = patches[0].model_copy(update={"revision_plan_id": uuid4()})
    with _scope(), pytest.raises(RevisionIntegrityError):
        await engine.revise(
            FakeSession(),
            tenant_id=TENANT,
            request=request,
            candidate=base,
            patches=(wrong_plan,),
            audit_event_id=AUDIT_ID,
            lock_owner="worker-c8",
            prompt_bundle_version="revision-prompt.v1",
            now=NOW,
        )
