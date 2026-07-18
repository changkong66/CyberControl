from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from liyans_contracts.artifacts import ArtifactObjectRefV1
from liyans_contracts.registry import CONTRACT_REGISTRY
from liyans_contracts.topic4_c2 import EmbeddingProfileV1
from liyans_contracts.topic4_c8 import RevisionOperation, RevisionPatchV1
from liyans_contracts.topic4_c9 import (
    SecurityDisposition,
    SecurityFindingCategory,
    SecurityFindingV1,
)
from liyans_contracts.topic4_c10 import PrivacyAction
from liyans_contracts.topic4_c12 import (
    AcceptanceDecision,
    AcceptanceGateResultV1,
    GateStatus,
    SystemAcceptanceReportV1,
)
from liyans_contracts.topic4_common import FindingSeverity
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
TOPIC4_OWNERS = {
    "c1-verification",
    "c2-knowledge",
    "c3-academic",
    "c4-graph",
    "c5-quiz",
    "c6-code",
    "c7-extension",
    "c8-revision",
    "c9-security",
    "c10-privacy",
    "c11-compliance",
    "c12-qa",
}
REQUIRED_RECORD_FIELDS = {
    "trace_id",
    "tenant_id",
    "version_cas",
    "record_sha256",
    "created_at",
    "immutable",
}


def _meta(*, digest: str = "a" * 64) -> dict[str, object]:
    return {
        "trace_id": "a" * 32,
        "tenant_id": "tenant-a",
        "version_cas": 1,
        "record_sha256": digest,
        "created_at": datetime.now(UTC),
        "immutable": True,
    }


def _artifact() -> ArtifactObjectRefV1:
    return ArtifactObjectRefV1(
        schema_version="artifact.object.ref.v1",
        storage_namespace="verification-artifacts",
        object_key=f"topic4/tests/{uuid4()}.json",
        media_type="application/json",
        content_encoding="identity",
        byte_size=128,
        sha256="b" * 64,
        created_at=datetime.now(UTC),
    )


def test_all_registered_topic4_records_are_strict_immutable_and_versioned() -> None:
    catalog = json.loads((ROOT / "config" / "contract-catalog.json").read_text(encoding="utf-8"))
    entries = {entry["schema_name"]: entry for entry in catalog["entries"]}
    topic4 = [
        registration for registration in CONTRACT_REGISTRY if registration.owner in TOPIC4_OWNERS
    ]

    assert topic4
    for registration in topic4:
        assert registration.model.model_fields.keys() >= REQUIRED_RECORD_FIELDS
        assert registration.model.model_config.get("extra") == "forbid"
        assert registration.model.model_config.get("frozen") is True
        assert entries[registration.schema_name]["status"] == "CODED_TOPIC4_FROZEN"


def test_embedding_profile_is_fixed_local_deterministic_2048() -> None:
    with pytest.raises(ValidationError):
        EmbeddingProfileV1(
            **_meta(),
            schema_version="embedding-profile.v1",
            embedding_profile_id=uuid4(),
            algorithm="HASHED_LEXICAL_2048",
            dimension=1024,
            tokenizer_version="tokenizer-v1",
            hash_seed_version="seed-v1",
            normalization="L2",
            signed_hashing=True,
            network_access=False,
        )


def test_cross_tenant_security_finding_is_non_waivable_block() -> None:
    with pytest.raises(ValidationError):
        SecurityFindingV1(
            **_meta(),
            schema_version="security-finding.v1",
            security_finding_id=uuid4(),
            verification_id=uuid4(),
            candidate_id=uuid4(),
            candidate_version=1,
            category=SecurityFindingCategory.CROSS_TENANT_REFERENCE,
            severity=FindingSeverity.CRITICAL,
            disposition=SecurityDisposition.REVIEW,
            detector="tenant-boundary",
            detector_version="v1",
            evidence_fingerprint_sha256="c" * 64,
            reason_code="CROSS_TENANT_REFERENCE",
            non_waivable=False,
        )


def test_revision_replacement_requires_artifact_and_hash() -> None:
    with pytest.raises(ValidationError):
        RevisionPatchV1(
            **_meta(),
            schema_version="revision-patch.v1",
            revision_patch_id=uuid4(),
            revision_plan_id=uuid4(),
            block_id="block-1",
            operation=RevisionOperation.REPLACE_BLOCK,
            base_block_sha256="c" * 64,
            target_content_schema_version="lecturer.block.v1",
            reason_claim_ids=[uuid4()],
        )


def test_system_acceptance_rejects_coverage_below_ninety_percent() -> None:
    gates = [
        AcceptanceGateResultV1(
            **_meta(digest=f"{index:064x}"),
            schema_version="acceptance-gate-result.v1",
            gate_code=f"G{index}",
            status=GateStatus.PASSED,
            evidence_artifact=_artifact(),
            evidence_sha256="d" * 64,
        )
        for index in range(13)
    ]
    with pytest.raises(ValidationError):
        SystemAcceptanceReportV1(
            **_meta(),
            schema_version="system-acceptance-report.v1",
            system_acceptance_report_id=uuid4(),
            build_commit_sha256="e" * 64,
            build_version="topic4-test",
            gate_results=gates,
            python_coverage_percent=89.99,
            concurrent_verifications=200,
            retrieval_p95_ms=199.0,
            publication_p95_ms=299.0,
            cross_tenant_leaks=0,
            authorization_replay_successes=0,
            critical_vulnerabilities=0,
            high_vulnerabilities=0,
            open_p0_defects=0,
            open_p1_defects=0,
            flaky_core_tests=0,
            decision=AcceptanceDecision.ACCEPTED,
            report_artifact=_artifact(),
            report_sha256="f" * 64,
        )


def test_privacy_action_enum_never_exposes_raw_value() -> None:
    assert set(PrivacyAction) == {
        PrivacyAction.ALLOW,
        PrivacyAction.TOKENIZE,
        PrivacyAction.REDACT,
        PrivacyAction.BLOCK,
    }
