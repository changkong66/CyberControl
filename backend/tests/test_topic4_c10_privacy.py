from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic3 import CandidateV1
from liyans_contracts.topic4_common import VerificationModule, VerificationVerdict
from test_topic4_c5_quiz import (
    TENANT,
    _candidate,
    _claim,
    _context,
    _evidence,
    _plan,
)

from liyans.domains.privacy.detector import DeterministicPIIDetector
from liyans.domains.privacy.evidence_source import PrivacyEvidenceBundle
from liyans.domains.privacy.handler import C10PrivacyHandler
from liyans.domains.verification.execution import BoundedModuleExecutor
from liyans.infrastructure.persistence.filesystem_artifacts import FileSystemArtifactObjectStore


@dataclass
class _FakeSource:
    bundle: PrivacyEvidenceBundle

    async def load(self, claim):
        return self.bundle


def _candidate_with_content(content_update: dict[str, object]) -> CandidateV1:
    candidate = _candidate()
    block = candidate.blocks[0]
    content = dict(block.content)
    content.update(content_update)
    updated_block = block.model_copy(
        update={"content": content, "content_sha256": canonical_sha256(content)}
    )
    document = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    document["blocks"] = [updated_block.model_dump(mode="json")]
    return CandidateV1(**document, candidate_sha256=canonical_sha256(document))


def _privacy_context(claim):
    context = _context(claim)
    dispatch = context.dispatch_item.model_copy(update={"module": VerificationModule.C10_PRIVACY})
    return replace(context, dispatch_item=dispatch)


def _bundle(candidate: CandidateV1, claim) -> PrivacyEvidenceBundle:
    evidence = _evidence(claim)
    return PrivacyEvidenceBundle(candidate, (evidence,), TENANT, evidence.knowledge_base_version_id)


@pytest.mark.asyncio
async def test_c10_clean_candidate_is_supported(tmp_path: Path) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    finding = await C10PrivacyHandler(
        _FakeSource(_bundle(candidate, claim)),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_privacy_context(claim))

    assert finding.verdict == VerificationVerdict.SUPPORTED
    assert finding.deterministic is True


@pytest.mark.asyncio
async def test_c10_tokenizes_and_redacts_pii_without_persisting_raw_values(tmp_path: Path) -> None:
    email = "alice" + "@example.edu"
    phone = "13800138000"
    candidate = _candidate_with_content({"student_email": email, "student_phone": phone})
    claim = _claim(candidate)
    store = FileSystemArtifactObjectStore(tmp_path)
    finding = await C10PrivacyHandler(
        _FakeSource(_bundle(candidate, claim)),
        store,
    ).verify(_privacy_context(claim))

    artifact = await store.read(
        tenant_id=TENANT,
        storage_namespace=finding.result_artifact.storage_namespace,
        object_key=finding.result_artifact.object_key,
        expected_byte_size=finding.result_artifact.byte_size,
        expected_sha256=finding.result_artifact.sha256,
    )
    document = json.loads(artifact)

    assert finding.verdict == VerificationVerdict.PARTIALLY_SUPPORTED
    assert "C10_EMAIL_PATTERN" in finding.finding_codes
    assert "C10_PHONE_PATTERN" in finding.finding_codes
    assert email.encode() not in artifact
    assert phone.encode() not in artifact
    assert document["raw_content_retained"] is False
    assert len(document["tokenized_values"]) == 2


@pytest.mark.asyncio
async def test_c10_critical_pii_is_non_waivable_and_blocked(tmp_path: Path) -> None:
    national_id = "110105" + "19491231" + "001X"
    candidate = _candidate_with_content({"national_id": national_id})
    claim = _claim(candidate)
    finding = await C10PrivacyHandler(
        _FakeSource(_bundle(candidate, claim)),
        FileSystemArtifactObjectStore(tmp_path),
    ).verify(_privacy_context(claim))

    assert finding.verdict == VerificationVerdict.UNSAFE
    assert "C10_NATIONAL_ID_FIELD" in finding.finding_codes


@pytest.mark.asyncio
async def test_c10_rejects_untrusted_tenant_and_missing_evidence(tmp_path: Path) -> None:
    candidate = _candidate()
    claim = _claim(candidate)
    evidence = _evidence(claim)
    store = FileSystemArtifactObjectStore(tmp_path)
    foreign = await C10PrivacyHandler(
        _FakeSource(PrivacyEvidenceBundle(candidate, (evidence,), "tenant-other")),
        store,
    ).verify(_privacy_context(claim))
    missing = await C10PrivacyHandler(
        _FakeSource(PrivacyEvidenceBundle(candidate, (), TENANT)),
        store,
    ).verify(_privacy_context(claim))

    assert foreign.verdict == VerificationVerdict.UNSAFE
    assert "C10_TENANT_ISOLATION_FAILED" in foreign.finding_codes
    assert missing.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


@pytest.mark.asyncio
async def test_c10_integrates_with_frozen_c1_executor(tmp_path: Path) -> None:
    candidate = _candidate_with_content({"student_name": "Alice"})
    claim = _claim(candidate)
    evidence = _evidence(claim)
    handler = C10PrivacyHandler(
        _FakeSource(PrivacyEvidenceBundle(candidate, (evidence,), TENANT)),
        FileSystemArtifactObjectStore(tmp_path),
    )
    context = _privacy_context(claim)
    execution = await BoundedModuleExecutor(
        {VerificationModule.C10_PRIVACY: handler},
        worker_instance_id="c10-test-worker",
        retry_backoff_ms=0,
    ).execute(
        _plan(claim).model_copy(update={"items": [context.dispatch_item]}),
        [claim],
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )

    assert execution.results[0].module == VerificationModule.C10_PRIVACY
    assert execution.results[0].verdict == VerificationVerdict.PARTIALLY_SUPPORTED


def test_c10_detector_is_bounded_and_deterministic() -> None:
    detector = DeterministicPIIDetector(max_matches=1)
    candidate = _candidate_with_content(
        {"student_email": "alice" + "@example.edu", "student_phone": "13800138000"}
    )

    first = detector.scan(candidate)
    second = detector.scan(candidate)

    assert len(first) == 1
    assert first == second
