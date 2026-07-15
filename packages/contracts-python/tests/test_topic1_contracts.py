from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic1 import (
    AuthoritySourceRefV1,
    CourseStatus,
    GoldenQuestionType,
    KnowledgePointStatus,
    MisconceptionSeverity,
    PrerequisiteType,
    TextbookMappingType,
    Topic1CourseV1,
    Topic1GoldenQuestionV1,
    Topic1GraphContentV1,
    Topic1GraphSnapshotV1,
    Topic1KnowledgePointV1,
    Topic1MisconceptionV1,
    Topic1PrerequisiteV1,
    Topic1TextbookMappingV1,
    Topic1TextbookSectionV1,
    Topic1TextbookV1,
)
from pydantic import ValidationError


def source() -> AuthoritySourceRefV1:
    return AuthoritySourceRefV1(
        source_id="TEXTBOOK_ATC",
        source_version="5e",
        locator="chapter-2",
        content_sha256="a" * 64,
    )


def course() -> Topic1CourseV1:
    now = datetime.now(UTC)
    return Topic1CourseV1(
        course_id="CRS_ATC_001",
        revision=1,
        course_code="ATC",
        title="Automatic Control Theory",
        description="Classical control foundations.",
        credit_hours=64,
        status=CourseStatus.ACTIVE,
        authority_sources=[source()],
        created_at=now,
        updated_at=now,
    )


def knowledge_point(kp_id: str) -> Topic1KnowledgePointV1:
    now = datetime.now(UTC)
    return Topic1KnowledgePointV1(
        kp_id=kp_id,
        course_id="CRS_ATC_001",
        revision=1,
        title=kp_id,
        summary="A canonical control-theory knowledge point.",
        learning_objectives=["Derive and apply the model."],
        category="MODELING",
        difficulty_level=2,
        difficulty_score=0.4,
        topology_level=0,
        topology_weight=0,
        estimated_minutes=90,
        status=KnowledgePointStatus.ACTIVE,
        authority_sources=[source()],
        created_at=now,
        updated_at=now,
    )


def test_graph_content_accepts_consistent_references() -> None:
    now = datetime.now(UTC)
    first = knowledge_point("KP_ATC_301_传递函数")
    second = knowledge_point("KP_ATC_302_时域响应")
    edge = Topic1PrerequisiteV1(
        edge_id="EDGE_ATC_001",
        course_id=first.course_id,
        prerequisite_kp_id=first.kp_id,
        dependent_kp_id=second.kp_id,
        relation_type=PrerequisiteType.REQUIRED,
        strength=1,
        rationale="Transfer functions precede response analysis.",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    content = Topic1GraphContentV1(
        course=course(),
        knowledge_points=[first, second],
        prerequisites=[edge],
    )
    snapshot = Topic1GraphSnapshotV1(
        snapshot_id=uuid4(),
        course_id=content.course.course_id,
        graph_version=1,
        content=content,
        content_sha256=canonical_sha256(content.model_dump(mode="json")),
        node_count=2,
        edge_count=1,
        created_by_subject="subject:test",
        frozen_at=now,
    )
    assert snapshot.node_count == 2


def test_graph_content_rejects_unknown_prerequisite_endpoint() -> None:
    now = datetime.now(UTC)
    first = knowledge_point("KP_ATC_301_传递函数")
    edge = Topic1PrerequisiteV1(
        edge_id="EDGE_ATC_001",
        course_id=first.course_id,
        prerequisite_kp_id=first.kp_id,
        dependent_kp_id="KP_ATC_999_不存在",
        relation_type=PrerequisiteType.REQUIRED,
        strength=1,
        rationale="Invalid edge.",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError, match="endpoints"):
        Topic1GraphContentV1(
            course=course(),
            knowledge_points=[first],
            prerequisites=[edge],
        )


def test_golden_question_references_must_exist_in_graph() -> None:
    now = datetime.now(UTC)
    question = Topic1GoldenQuestionV1(
        question_id="QUESTION_ATC_001",
        primary_kp_id="KP_ATC_301_传递函数",
        question_type=GoldenQuestionType.CALCULATION,
        stem_markdown="Find the transfer function.",
        answer_document={"value": "1/(s+1)"},
        solution_markdown="Apply the Laplace transform.",
        difficulty_level=2,
        discrimination=0.7,
        diagnostic_tags=["laplace"],
        misconception_ids=["MISCONCEPTION_ATC_999"],
        authority_sources=[source()],
        revision=1,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError, match="misconceptions"):
        Topic1GraphContentV1(
            course=course(),
            knowledge_points=[knowledge_point(question.primary_kp_id)],
            prerequisites=[],
            golden_questions=[question],
        )


def test_prerequisite_rejects_self_edge() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="depend on itself"):
        Topic1PrerequisiteV1(
            edge_id="EDGE_ATC_001",
            course_id="CRS_ATC_001",
            prerequisite_kp_id="KP_ATC_301_传递函数",
            dependent_kp_id="KP_ATC_301_传递函数",
            relation_type=PrerequisiteType.REQUIRED,
            strength=1,
            rationale="Invalid self edge.",
            revision=1,
            created_at=now,
            updated_at=now,
        )


def test_textbook_section_rejects_reversed_pages() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="end_page"):
        Topic1TextbookSectionV1(
            section_id="SECTION_ATC_001",
            textbook_id="TEXTBOOK_ATC_001",
            chapter_number="2.1",
            title="Transfer Functions",
            start_page=50,
            end_page=40,
            revision=1,
            created_at=now,
            updated_at=now,
        )


def test_snapshot_rejects_incorrect_counts() -> None:
    now = datetime.now(UTC)
    content = Topic1GraphContentV1(
        course=course(),
        knowledge_points=[knowledge_point("KP_ATC_301_传递函数")],
        prerequisites=[],
    )
    with pytest.raises(ValidationError, match="node_count"):
        Topic1GraphSnapshotV1(
            snapshot_id=uuid4(),
            course_id=content.course.course_id,
            graph_version=1,
            content=content,
            content_sha256="b" * 64,
            node_count=0,
            edge_count=0,
            created_by_subject="subject:test",
            frozen_at=now,
        )


def test_graph_content_rejects_duplicate_prerequisite_relation() -> None:
    now = datetime.now(UTC)
    first = knowledge_point("KP_ATC_301_传递函数")
    second = knowledge_point("KP_ATC_302_时域响应")
    edge = Topic1PrerequisiteV1(
        edge_id="EDGE_ATC_001",
        course_id=first.course_id,
        prerequisite_kp_id=first.kp_id,
        dependent_kp_id=second.kp_id,
        relation_type=PrerequisiteType.REQUIRED,
        strength=1,
        rationale="Transfer functions precede response analysis.",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError, match="prerequisite relation"):
        Topic1GraphContentV1(
            course=course(),
            knowledge_points=[first, second],
            prerequisites=[edge, edge.model_copy(update={"edge_id": "EDGE_ATC_002"})],
        )


def test_graph_content_rejects_missing_or_cyclic_section_parent() -> None:
    now = datetime.now(UTC)
    textbook = Topic1TextbookV1(
        textbook_id="TEXTBOOK_ATC_001",
        title="Principles of Automatic Control",
        authors=["Control Faculty"],
        publisher="Higher Education Press",
        edition="5",
        publication_year=2025,
        authority_level=5,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    first = Topic1TextbookSectionV1(
        section_id="SECTION_ATC_001",
        textbook_id=textbook.textbook_id,
        parent_section_id="SECTION_ATC_002",
        chapter_number="2",
        title="System Modeling",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError, match="parent must exist"):
        Topic1GraphContentV1(
            course=course(),
            knowledge_points=[],
            prerequisites=[],
            textbooks=[textbook],
            textbook_sections=[first],
        )
    second = first.model_copy(
        update={
            "section_id": "SECTION_ATC_002",
            "parent_section_id": first.section_id,
        }
    )
    with pytest.raises(ValidationError, match="hierarchy contains a cycle"):
        Topic1GraphContentV1(
            course=course(),
            knowledge_points=[],
            prerequisites=[],
            textbooks=[textbook],
            textbook_sections=[first, second],
        )


def test_graph_content_rejects_duplicate_mapping_relation() -> None:
    now = datetime.now(UTC)
    kp = knowledge_point("KP_ATC_301_传递函数")
    textbook = Topic1TextbookV1(
        textbook_id="TEXTBOOK_ATC_001",
        title="Principles of Automatic Control",
        authors=["Control Faculty"],
        publisher="Higher Education Press",
        edition="5",
        publication_year=2025,
        authority_level=5,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    section = Topic1TextbookSectionV1(
        section_id="SECTION_ATC_001",
        textbook_id=textbook.textbook_id,
        chapter_number="2.1",
        title="Transfer Functions",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    mapping = Topic1TextbookMappingV1(
        mapping_id="MAPPING_ATC_001",
        kp_id=kp.kp_id,
        section_id=section.section_id,
        mapping_type=TextbookMappingType.PRIMARY,
        coverage=1,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError, match="mapping relation"):
        Topic1GraphContentV1(
            course=course(),
            knowledge_points=[kp],
            prerequisites=[],
            textbooks=[textbook],
            textbook_sections=[section],
            textbook_mappings=[
                mapping,
                mapping.model_copy(update={"mapping_id": "MAPPING_ATC_002"}),
            ],
        )


def test_graph_content_rejects_duplicate_question_references() -> None:
    now = datetime.now(UTC)
    first = knowledge_point("KP_ATC_301_传递函数")
    second = knowledge_point("KP_ATC_302_时域响应")
    misconception = Topic1MisconceptionV1(
        misconception_id="MISCONCEPTION_ATC_001",
        kp_id=first.kp_id,
        title="Pole sign error",
        description="The pole sign is copied into the time constant.",
        trigger_pattern="Uses tau = pole.",
        diagnosis_tags=["sign-error"],
        remediation_hint="Rewrite the first-order factor.",
        severity=MisconceptionSeverity.HIGH,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    question = Topic1GoldenQuestionV1(
        question_id="QUESTION_ATC_001",
        primary_kp_id=first.kp_id,
        related_kp_ids=[second.kp_id, second.kp_id],
        question_type=GoldenQuestionType.CALCULATION,
        stem_markdown="Find the response.",
        answer_document={"value": "1-exp(-t)"},
        solution_markdown="Apply the inverse Laplace transform.",
        difficulty_level=2,
        discrimination=0.7,
        diagnostic_tags=["laplace"],
        misconception_ids=[misconception.misconception_id],
        authority_sources=[source()],
        revision=1,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError, match="related knowledge point"):
        Topic1GraphContentV1(
            course=course(),
            knowledge_points=[first, second],
            prerequisites=[],
            misconceptions=[misconception],
            golden_questions=[question],
        )


def test_snapshot_rejects_course_and_edge_count_mismatch() -> None:
    now = datetime.now(UTC)
    content = Topic1GraphContentV1(
        course=course(),
        knowledge_points=[knowledge_point("KP_ATC_301_传递函数")],
        prerequisites=[],
    )
    base = {
        "snapshot_id": uuid4(),
        "content": content,
        "content_sha256": "b" * 64,
        "node_count": 1,
        "created_by_subject": "subject:test",
        "frozen_at": now,
    }
    with pytest.raises(ValidationError, match="course_id"):
        Topic1GraphSnapshotV1(
            course_id="CRS_ATC_999",
            graph_version=1,
            edge_count=0,
            **base,
        )
    with pytest.raises(ValidationError, match="edge_count"):
        Topic1GraphSnapshotV1(
            course_id=content.course.course_id,
            graph_version=1,
            edge_count=1,
            **base,
        )


def test_snapshot_rejects_content_digest_mismatch() -> None:
    now = datetime.now(UTC)
    content = Topic1GraphContentV1(
        course=course(),
        knowledge_points=[knowledge_point("KP_ATC_301_传递函数")],
        prerequisites=[],
    )
    with pytest.raises(ValidationError, match="content_sha256"):
        Topic1GraphSnapshotV1(
            snapshot_id=uuid4(),
            course_id=content.course.course_id,
            graph_version=1,
            content=content,
            content_sha256="b" * 64,
            node_count=1,
            edge_count=0,
            created_by_subject="subject:test",
            frozen_at=now,
        )
