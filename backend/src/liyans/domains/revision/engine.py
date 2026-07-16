from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.common import canonical_sha256
from liyans_contracts.enums import VerificationTrigger
from liyans_contracts.topic3 import (
    BlockStatus,
    BlockType,
    BlockV1,
    CandidateStatus,
    CandidateV1,
    CodeSandboxContentV1,
    ExtensionContentV1,
    LecturerContentV1,
    MindMapContentV1,
    TesterContentV1,
)
from liyans_contracts.topic4_c1 import RevisionRequestV1, RevisionResponseV1
from liyans_contracts.topic4_c8 import (
    RevisionCycleState,
    RevisionCycleV1,
    RevisionOperation,
    RevisionPatchV1,
    RevisionPlanV1,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from liyans.core.tenant import assert_tenant
from liyans.domains.topic3.entities import CandidateRecord
from liyans.domains.topic3.repository import Topic3Repository
from liyans.domains.verification.records import build_topic4_record, record_integrity_valid

from .repository import RevisionRepository


class RevisionError(ValueError):
    """Fail-closed C8 validation error."""


class RevisionConflictError(RevisionError):
    """The request races with another revision or uses stale data."""


class RevisionLimitError(RevisionError):
    """The immutable two-round revision budget has been exhausted."""


class RevisionIntegrityError(RevisionError):
    """A candidate, block, artifact, or contract digest is inconsistent."""


class RevisionArtifactReader(Protocol):
    async def read(
        self,
        *,
        tenant_id: str,
        storage_namespace: str,
        object_key: str,
        expected_byte_size: int,
        expected_sha256: str,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ReverificationCommand:
    """Minimal C1 hand-off; C1 owns construction and persistence of its request."""

    verification_id: UUID
    parent_verification_id: UUID
    candidate_id: UUID
    candidate_version: int
    candidate_sha256: str
    revision_round: int
    trace_id: str
    tenant_id: str
    trigger: VerificationTrigger = VerificationTrigger.REVISION_REVERIFY

    def as_document(self) -> dict[str, Any]:
        return {
            "schema_version": "topic4.reverification.command.v1",
            "verification_id": str(self.verification_id),
            "parent_verification_id": str(self.parent_verification_id),
            "candidate_id": str(self.candidate_id),
            "candidate_version": self.candidate_version,
            "candidate_sha256": self.candidate_sha256,
            "revision_round": self.revision_round,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "trigger": self.trigger.value,
        }


@dataclass(frozen=True, slots=True)
class RevisionOutcome:
    cycle: RevisionCycleV1
    plan: RevisionPlanV1
    patches: tuple[RevisionPatchV1, ...]
    candidate: CandidateRecord
    response: RevisionResponseV1
    reverification: ReverificationCommand


CONTENT_MODELS: dict[str, type[BaseModel]] = {
    "topic3.lecturer-content.v1": LecturerContentV1,
    "topic3.mindmap-content.v1": MindMapContentV1,
    "topic3.tester-content.v1": TesterContentV1,
    "topic3.code-sandbox-content.v1": CodeSandboxContentV1,
    "topic3.extension-content.v1": ExtensionContentV1,
}

BLOCK_SCHEMA_TYPES: dict[str, BlockType] = {
    "topic3.lecturer-content.v1": BlockType.MARKDOWN,
    "topic3.mindmap-content.v1": BlockType.MERMAID,
    "topic3.tester-content.v1": BlockType.QUIZ,
    "topic3.code-sandbox-content.v1": BlockType.CODE,
    "topic3.extension-content.v1": BlockType.EXTENSION,
}


class RevisionEngine:
    """Deterministic two-round immutable candidate revision coordinator.

    The caller must invoke this object inside the existing C1 SERIALIZABLE
    transaction. C8 never commits, publishes Outbox messages, or mutates a
    historical row itself.
    """

    def __init__(
        self,
        revision_repository: RevisionRepository,
        topic3_repository: Topic3Repository,
        artifact_store: RevisionArtifactReader,
        *,
        lock_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        if not timedelta(seconds=1) <= lock_ttl <= timedelta(hours=1):
            raise ValueError("lock_ttl must be between one second and one hour")
        self._repository = revision_repository
        self._topic3_repository = topic3_repository
        self._artifact_store = artifact_store
        self._lock_ttl = lock_ttl

    async def revise(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        request: RevisionRequestV1,
        candidate: CandidateRecord | CandidateV1,
        patches: Sequence[RevisionPatchV1],
        audit_event_id: UUID,
        lock_owner: str,
        prompt_bundle_version: str,
        now: datetime | None = None,
    ) -> RevisionOutcome:
        assert_tenant(tenant_id)
        if not lock_owner or len(lock_owner) > 128:
            raise ValueError("lock_owner must contain 1 to 128 characters")
        if not prompt_bundle_version:
            raise ValueError("prompt_bundle_version is required")
        timestamp = now or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        candidate_value = (
            candidate.candidate if isinstance(candidate, CandidateRecord) else candidate
        )
        self._validate_request_binding(tenant_id, request, candidate_value, timestamp)
        self._validate_patch_set(request, patches)

        replay = await self._repository.find_completed_request(
            session,
            tenant_id,
            request.revision_request_id,
        )
        if replay is not None:
            return self._replay_outcome(replay)

        async with self._repository.candidate_lock(
            session,
            tenant_id,
            candidate_value.candidate_id,
        ):
            replay = await self._repository.find_completed_request(
                session,
                tenant_id,
                request.revision_request_id,
            )
            if replay is not None:
                return self._replay_outcome(replay)

            self._validate_round_budget(request, candidate_value)
            await self._verify_artifact(
                tenant_id,
                request.instructions_artifact,
                request.instructions_sha256,
            )
            replacement_blocks = await self._load_replacement_blocks(
                tenant_id,
                candidate_value,
                patches,
            )
            revised_candidate = self._build_candidate(
                candidate_value,
                patches,
                replacement_blocks,
                timestamp,
            )
            cycle_id = uuid5(request.revision_request_id, "topic4-c8-cycle")
            plan_id = uuid5(cycle_id, "topic4-c8-plan")
            lock_token = uuid4()
            lock_expires_at = timestamp + self._lock_ttl
            locked_cycle = self._cycle(
                request,
                candidate_value,
                cycle_id=cycle_id,
                state=RevisionCycleState.LOCKED,
                version=1,
                lock_token=lock_token,
                lock_owner=lock_owner,
                lock_expires_at=lock_expires_at,
                created_at=timestamp,
            )
            await self._repository.append_cycle(session, tenant_id, locked_cycle, audit_event_id)

            plan = build_topic4_record(
                RevisionPlanV1,
                trace_id=request.trace_id,
                tenant_id=tenant_id,
                version_cas=1,
                created_at=timestamp,
                immutable=True,
                schema_version="revision-plan.v1",
                revision_plan_id=plan_id,
                revision_cycle_id=cycle_id,
                verification_id=request.verification_id,
                candidate_id=candidate_value.candidate_id,
                base_candidate_version=candidate_value.candidate_version,
                base_candidate_sha256=candidate_value.candidate_sha256,
                revision_round=request.revision_round,
                target_agent=request.target_agent,
                affected_claim_ids=sorted(request.claim_ids, key=str),
                affected_block_ids=sorted(request.block_ids),
                patch_ids=[patch.revision_patch_id for patch in patches],
                instructions_artifact=request.instructions_artifact,
                instructions_sha256=request.instructions_sha256,
                prompt_bundle_version=prompt_bundle_version,
            )
            if any(patch.revision_plan_id != plan_id for patch in patches):
                raise RevisionIntegrityError("patches must reference the derived immutable plan id")
            await self._repository.append_plan(
                session,
                tenant_id,
                plan,
                locked_cycle.version_cas,
                audit_event_id,
            )
            for patch in patches:
                await self._repository.append_patch(session, tenant_id, patch, audit_event_id)

            generating_cycle = self._cycle(
                request,
                candidate_value,
                cycle_id=cycle_id,
                state=RevisionCycleState.GENERATING,
                version=2,
                lock_token=lock_token,
                lock_owner=lock_owner,
                lock_expires_at=lock_expires_at,
                created_at=timestamp,
            )
            await self._repository.append_cycle(
                session,
                tenant_id,
                generating_cycle,
                audit_event_id,
            )
            candidate_record = CandidateRecord(
                candidate_record_id=uuid5(
                    revised_candidate.candidate_id,
                    f"candidate-record-v{revised_candidate.candidate_version}",
                ),
                candidate=revised_candidate,
                frozen_at=timestamp,
            )
            await self._topic3_repository.append_candidate(
                session,
                tenant_id,
                candidate_record,
                audit_event_id,
            )

            child_verification_id = uuid5(
                request.verification_id,
                f"topic4-c8-reverify:{revised_candidate.candidate_version}:{revised_candidate.candidate_sha256}",
            )
            reverification = ReverificationCommand(
                verification_id=child_verification_id,
                parent_verification_id=request.verification_id,
                candidate_id=revised_candidate.candidate_id,
                candidate_version=revised_candidate.candidate_version,
                candidate_sha256=revised_candidate.candidate_sha256,
                revision_round=request.revision_round,
                trace_id=request.trace_id,
                tenant_id=tenant_id,
            )
            response = await self._build_response(
                tenant_id,
                request,
                candidate_record,
                plan,
                patches,
                reverification,
                timestamp,
            )
            completed_cycle = self._cycle(
                request,
                candidate_value,
                cycle_id=cycle_id,
                state=RevisionCycleState.COMPLETED,
                version=3,
                lock_token=lock_token,
                lock_owner=lock_owner,
                lock_expires_at=lock_expires_at,
                created_at=timestamp,
                completed_at=timestamp,
                document={
                    "revision_request_id": str(request.revision_request_id),
                    "plan": plan.model_dump(mode="json"),
                    "patches": [patch.model_dump(mode="json") for patch in patches],
                    "candidate": revised_candidate.model_dump(mode="json"),
                    "response": response.model_dump(mode="json"),
                    "reverification": reverification.as_document(),
                },
            )
            await self._repository.append_cycle(
                session,
                tenant_id,
                completed_cycle,
                audit_event_id,
                document={
                    "revision_request_id": str(request.revision_request_id),
                    "plan": plan.model_dump(mode="json"),
                    "patches": [patch.model_dump(mode="json") for patch in patches],
                    "candidate": revised_candidate.model_dump(mode="json"),
                    "response": response.model_dump(mode="json"),
                    "reverification": reverification.as_document(),
                },
            )
            return RevisionOutcome(
                cycle=completed_cycle,
                plan=plan,
                patches=tuple(patches),
                candidate=candidate_record,
                response=response,
                reverification=reverification,
            )

    @staticmethod
    def _validate_request_binding(
        tenant_id: str,
        request: RevisionRequestV1,
        candidate: CandidateV1,
        now: datetime,
    ) -> None:
        if request.tenant_id != tenant_id:
            raise RevisionIntegrityError("revision request tenant does not match trusted context")
        if request.original_candidate_id != candidate.candidate_id:
            raise RevisionConflictError("revision request candidate id is stale")
        if request.original_candidate_version != candidate.candidate_version:
            raise RevisionConflictError("revision request candidate version is stale")
        if request.original_candidate_sha256 != candidate.candidate_sha256:
            raise RevisionIntegrityError("revision request candidate sha256 is stale")
        if request.target_agent != candidate.provenance.agent:
            raise RevisionIntegrityError("revision target agent does not own the Candidate")
        if now >= request.deadline_at:
            raise RevisionConflictError("revision request deadline has expired")
        if candidate.status != CandidateStatus.COMPLETE:
            raise RevisionConflictError("only a complete Candidate can be revised")

    @staticmethod
    def _validate_round_budget(request: RevisionRequestV1, candidate: CandidateV1) -> None:
        if request.revision_round != candidate.candidate_version:
            raise RevisionConflictError(
                "revision round must equal the immutable Candidate version being revised"
            )
        if request.revision_round > 2:
            raise RevisionLimitError("a Candidate may be revised at most twice")

    @staticmethod
    def _validate_patch_set(
        request: RevisionRequestV1,
        patches: Sequence[RevisionPatchV1],
    ) -> None:
        if not patches:
            raise RevisionIntegrityError("a revision requires at least one patch")
        requested_blocks = set(request.block_ids)
        requested_claims = set(request.claim_ids)
        patch_blocks = [patch.block_id for patch in patches]
        if len(patch_blocks) != len(set(patch_blocks)):
            raise RevisionIntegrityError("a block may appear in only one revision patch")
        if set(patch_blocks) != requested_blocks:
            raise RevisionIntegrityError("patch block ids must exactly match the revision request")
        plan_id = patches[0].revision_plan_id
        for patch in patches:
            if patch.tenant_id != request.tenant_id or patch.trace_id != request.trace_id:
                raise RevisionIntegrityError(
                    "patch tenant or trace binding does not match the request"
                )
            if patch.revision_plan_id != plan_id:
                raise RevisionIntegrityError("all patches must belong to one immutable plan")
            if not set(patch.reason_claim_ids) <= requested_claims:
                raise RevisionIntegrityError(
                    "patch references a claim outside the revision request"
                )

    async def _load_replacement_blocks(
        self,
        tenant_id: str,
        candidate: CandidateV1,
        patches: Sequence[RevisionPatchV1],
    ) -> dict[str, BlockV1]:
        blocks = {block.block_id: block for block in candidate.blocks}
        replacements: dict[str, BlockV1] = {}
        for patch in patches:
            base = blocks.get(patch.block_id)
            if base is None:
                raise RevisionConflictError(f"unknown Candidate block: {patch.block_id}")
            if base.content_sha256 != patch.base_block_sha256:
                raise RevisionConflictError(f"stale block sha256 for {patch.block_id}")
            if patch.operation == RevisionOperation.REMOVE_BLOCK:
                if base.status not in {BlockStatus.FAILED, BlockStatus.SUPERSEDED}:
                    raise RevisionIntegrityError(
                        "only terminal failed or superseded blocks may be removed"
                    )
                if any(patch.block_id in other.dependency_block_ids for other in candidate.blocks):
                    raise RevisionIntegrityError("removed block would leave a dangling dependency")
                continue
            assert patch.replacement_artifact is not None
            assert patch.replacement_sha256 is not None
            raw = await self._artifact_store.read(
                tenant_id=tenant_id,
                storage_namespace=patch.replacement_artifact.storage_namespace,
                object_key=patch.replacement_artifact.object_key,
                expected_byte_size=patch.replacement_artifact.byte_size,
                expected_sha256=patch.replacement_artifact.sha256,
            )
            try:
                payload = json.loads(raw.decode("utf-8"))
                replacement = BlockV1.model_validate(payload)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise RevisionIntegrityError(
                    "replacement artifact is not a valid Topic3 Block"
                ) from exc
            self._validate_replacement_block(base, replacement, patch)
            replacements[patch.block_id] = replacement
        return replacements

    async def _verify_artifact(
        self,
        tenant_id: str,
        artifact: ArtifactObjectRefV1,
        expected_sha256: str,
    ) -> None:
        if artifact.sha256 != expected_sha256:
            raise RevisionIntegrityError(
                "artifact reference hash does not match the contract binding"
            )
        await self._artifact_store.read(
            tenant_id=tenant_id,
            storage_namespace=artifact.storage_namespace,
            object_key=artifact.object_key,
            expected_byte_size=artifact.byte_size,
            expected_sha256=artifact.sha256,
        )

    @staticmethod
    def _validate_replacement_block(
        base: BlockV1,
        replacement: BlockV1,
        patch: RevisionPatchV1,
    ) -> None:
        if replacement.block_id != base.block_id or replacement.block_type != base.block_type:
            raise RevisionIntegrityError("replacement cannot change block identity or type")
        if replacement.content_schema_version != patch.target_content_schema_version:
            raise RevisionIntegrityError("replacement content schema does not match the patch")
        if replacement.content_schema_version != base.content_schema_version:
            raise RevisionIntegrityError(
                "replacement cannot change the frozen Topic3 content schema"
            )
        expected_type = BLOCK_SCHEMA_TYPES.get(replacement.content_schema_version)
        if expected_type != replacement.block_type:
            raise RevisionIntegrityError("replacement block type does not own its content schema")
        content_model = CONTENT_MODELS.get(replacement.content_schema_version)
        if content_model is None:
            raise RevisionIntegrityError("replacement content schema is not frozen")
        try:
            parsed = content_model.model_validate(replacement.content)
        except ValueError as exc:
            raise RevisionIntegrityError(
                "replacement content violates the frozen Topic3 schema"
            ) from exc
        if parsed.model_dump(mode="json") != replacement.content:
            raise RevisionIntegrityError(
                "replacement content was normalized instead of validated exactly"
            )
        if patch.replacement_sha256 != replacement.content_sha256:
            raise RevisionIntegrityError("replacement content sha256 does not match the patch")
        if replacement.dependency_block_ids != base.dependency_block_ids:
            raise RevisionIntegrityError("revision cannot change block dependency topology")

    @staticmethod
    def _build_candidate(
        candidate: CandidateV1,
        patches: Sequence[RevisionPatchV1],
        replacements: dict[str, BlockV1],
        now: datetime,
    ) -> CandidateV1:
        patch_by_block = {patch.block_id: patch for patch in patches}
        blocks: list[BlockV1] = []
        for block in candidate.blocks:
            patch = patch_by_block.get(block.block_id)
            if patch is not None and patch.operation == RevisionOperation.REMOVE_BLOCK:
                continue
            next_block = replacements.get(block.block_id, block)
            blocks.append(
                next_block.model_copy(
                    update={
                        "ordinal": len(blocks),
                        "title": block.title,
                        "dependency_block_ids": block.dependency_block_ids,
                        "status": BlockStatus.COMPLETE,
                        "created_at": now,
                    }
                )
            )
        if not blocks:
            raise RevisionIntegrityError("a revised Candidate must retain at least one block")
        draft = candidate.model_copy(
            update={
                "candidate_version": candidate.candidate_version + 1,
                "parent_candidate_version": candidate.candidate_version,
                "status": CandidateStatus.COMPLETE,
                "blocks": blocks,
                "created_at": now,
                "candidate_sha256": "0" * 64,
            }
        )
        digest = canonical_sha256(draft.model_dump(mode="json", exclude={"candidate_sha256"}))
        return CandidateV1.model_validate(
            draft.model_copy(update={"candidate_sha256": digest}).model_dump(mode="json")
        )

    async def _build_response(
        self,
        tenant_id: str,
        request: RevisionRequestV1,
        candidate: CandidateRecord,
        plan: RevisionPlanV1,
        patches: Sequence[RevisionPatchV1],
        reverification: ReverificationCommand,
        now: datetime,
    ) -> RevisionResponseV1:
        payload = {
            "schema_version": "topic4.revision-response-artifact.v1",
            "revision_request_id": str(request.revision_request_id),
            "plan": plan.model_dump(mode="json"),
            "patches": [patch.model_dump(mode="json") for patch in patches],
            "candidate": candidate.candidate.model_dump(mode="json"),
            "reverification": reverification.as_document(),
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = sha256(content).hexdigest()
        stored = await self._artifact_store.put(
            tenant_id=tenant_id,
            storage_namespace="verification-artifacts",
            object_key=(
                f"c8/revisions/{candidate.candidate.candidate_id}/"
                f"{candidate.candidate.candidate_version}/{digest}.json"
            ),
            content=content,
        )
        if stored.sha256 != digest or stored.byte_size != len(content):
            raise RevisionIntegrityError("response artifact store returned inconsistent metadata")
        artifact = ArtifactObjectRefV1(
            schema_version="artifact.object.ref.v1",
            storage_namespace="verification-artifacts",
            object_key=stored.object_key,
            media_type="application/json",
            content_encoding="identity",
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            created_at=now,
        )
        response = build_topic4_record(
            RevisionResponseV1,
            trace_id=request.trace_id,
            tenant_id=tenant_id,
            version_cas=request.revision_round,
            created_at=now,
            immutable=True,
            schema_version="revision.response.v1",
            revision_response_id=uuid5(request.revision_request_id, "topic4-c8-response"),
            revision_request_id=request.revision_request_id,
            child_verification_id=reverification.verification_id,
            revised_candidate_id=candidate.candidate.candidate_id,
            revised_candidate_version=candidate.candidate.candidate_version,
            revised_candidate_sha256=candidate.candidate.candidate_sha256,
            changed_block_ids=sorted({patch.block_id for patch in patches}),
            response_artifact=artifact,
            response_sha256=stored.sha256,
            completed_at=now,
        )
        return response

    @staticmethod
    def _cycle(
        request: RevisionRequestV1,
        candidate: CandidateV1,
        *,
        cycle_id: UUID,
        state: RevisionCycleState,
        version: int,
        lock_token: UUID,
        lock_owner: str,
        lock_expires_at: datetime,
        created_at: datetime,
        completed_at: datetime | None = None,
        document: dict[str, Any] | None = None,
    ) -> RevisionCycleV1:
        return build_topic4_record(
            RevisionCycleV1,
            trace_id=request.trace_id,
            tenant_id=request.tenant_id,
            version_cas=version,
            created_at=created_at,
            immutable=True,
            schema_version="revision-cycle.v1",
            revision_cycle_id=cycle_id,
            verification_id=request.verification_id,
            parent_verification_id=request.parent_verification_id,
            candidate_id=candidate.candidate_id,
            base_candidate_version=candidate.candidate_version,
            base_candidate_sha256=candidate.candidate_sha256,
            revision_round=request.revision_round,
            state=state,
            lock_token=lock_token,
            lock_owner=lock_owner,
            lock_expires_at=lock_expires_at,
            completed_at=completed_at,
        )

    @staticmethod
    def _replay_outcome(document: dict[str, Any]) -> RevisionOutcome:
        try:
            plan = RevisionPlanV1.model_validate(document["plan"])
            patches = tuple(RevisionPatchV1.model_validate(value) for value in document["patches"])
            candidate = CandidateV1.model_validate(document["candidate"])
            response = RevisionResponseV1.model_validate(document["response"])
            command_document = document["reverification"]
            command = ReverificationCommand(
                verification_id=UUID(command_document["verification_id"]),
                parent_verification_id=UUID(command_document["parent_verification_id"]),
                candidate_id=UUID(command_document["candidate_id"]),
                candidate_version=int(command_document["candidate_version"]),
                candidate_sha256=command_document["candidate_sha256"],
                revision_round=int(command_document["revision_round"]),
                trace_id=command_document["trace_id"],
                tenant_id=command_document["tenant_id"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RevisionIntegrityError(
                "stored C8 replay document failed contract validation"
            ) from exc
        cycle_document = document.get("cycle")
        if not isinstance(cycle_document, dict):
            raise RevisionIntegrityError("stored C8 replay document has no cycle record")
        cycle = RevisionCycleV1.model_validate(cycle_document)
        if not all(record_integrity_valid(record) for record in (cycle, plan, *patches, response)):
            raise RevisionIntegrityError("stored C8 replay record hash validation failed")
        return RevisionOutcome(
            cycle=cycle,
            plan=plan,
            patches=patches,
            candidate=CandidateRecord(
                candidate_record_id=uuid5(
                    candidate.candidate_id,
                    f"candidate-record-v{candidate.candidate_version}",
                ),
                candidate=candidate,
                frozen_at=candidate.created_at,
            ),
            response=response,
            reverification=command,
        )
