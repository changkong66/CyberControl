from __future__ import annotations

from collections.abc import Hashable
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

from .common import FROZEN_MODEL_CONFIG, Sha256Hex, canonical_sha256

CourseId = Annotated[
    str,
    StringConstraints(pattern=r"^CRS_[A-Z0-9_]{3,60}$", min_length=7, max_length=64),
]
KnowledgePointId = Annotated[
    str,
    StringConstraints(pattern=r"^KP_\S{3,117}$", min_length=6, max_length=120),
]
Topic1EntityId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_:-]{5,127}$", min_length=6, max_length=128),
]


class CourseStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class KnowledgePointStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class PrerequisiteType(StrEnum):
    REQUIRED = "REQUIRED"
    RECOMMENDED = "RECOMMENDED"
    SUPPORTING = "SUPPORTING"


class MisconceptionSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TextbookMappingType(StrEnum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    EXAMPLE = "EXAMPLE"
    EXERCISE = "EXERCISE"


class GoldenQuestionType(StrEnum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    CALCULATION = "CALCULATION"
    PROOF = "PROOF"
    DESIGN = "DESIGN"
    SIMULATION = "SIMULATION"


class AuthoritySourceRefV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    source_id: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=128)
    locator: str = Field(min_length=1, max_length=512)
    content_sha256: Sha256Hex | None = None


class Topic1CourseV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.course.v1"] = "topic1.course.v1"
    course_id: CourseId
    revision: int = Field(ge=1)
    course_code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="zh-CN", min_length=2, max_length=16)
    academic_level: str = Field(default="UNDERGRADUATE", min_length=2, max_length=32)
    credit_hours: float = Field(ge=0, le=256)
    status: CourseStatus
    authority_sources: list[AuthoritySourceRefV1] = Field(default_factory=list, max_length=64)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Topic1KnowledgePointV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.knowledge-point.v1"] = "topic1.knowledge-point.v1"
    kp_id: KnowledgePointId
    course_id: CourseId
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    summary: str = Field(min_length=1, max_length=4000)
    learning_objectives: list[str] = Field(min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=128)
    difficulty_level: int = Field(ge=1, le=5)
    difficulty_score: float = Field(ge=0, le=1)
    topology_level: int = Field(ge=0)
    topology_weight: float = Field(ge=0, le=1)
    estimated_minutes: int = Field(ge=1, le=2400)
    formula_signatures: list[str] = Field(default_factory=list, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=64)
    status: KnowledgePointStatus
    authority_sources: list[AuthoritySourceRefV1] = Field(default_factory=list, max_length=64)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Topic1PrerequisiteV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.prerequisite.v1"] = "topic1.prerequisite.v1"
    edge_id: Topic1EntityId
    course_id: CourseId
    prerequisite_kp_id: KnowledgePointId
    dependent_kp_id: KnowledgePointId
    relation_type: PrerequisiteType
    strength: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=2000)
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def reject_self_edge(self) -> Topic1PrerequisiteV1:
        if self.prerequisite_kp_id == self.dependent_kp_id:
            raise ValueError("a knowledge point cannot depend on itself")
        return self


class Topic1MisconceptionV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.misconception.v1"] = "topic1.misconception.v1"
    misconception_id: Topic1EntityId
    kp_id: KnowledgePointId
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=4000)
    trigger_pattern: str = Field(min_length=1, max_length=2000)
    diagnosis_tags: list[str] = Field(min_length=1, max_length=32)
    remediation_hint: str = Field(min_length=1, max_length=4000)
    severity: MisconceptionSeverity
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Topic1TextbookV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.textbook.v1"] = "topic1.textbook.v1"
    textbook_id: Topic1EntityId
    title: str = Field(min_length=1, max_length=512)
    authors: list[str] = Field(min_length=1, max_length=32)
    publisher: str = Field(min_length=1, max_length=255)
    edition: str = Field(min_length=1, max_length=64)
    isbn: str | None = Field(default=None, min_length=10, max_length=32)
    publication_year: int = Field(ge=1900, le=2200)
    authority_level: int = Field(ge=1, le=5)
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Topic1TextbookSectionV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.textbook-section.v1"] = "topic1.textbook-section.v1"
    section_id: Topic1EntityId
    textbook_id: Topic1EntityId
    parent_section_id: Topic1EntityId | None = None
    chapter_number: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_page_range(self) -> Topic1TextbookSectionV1:
        if (
            self.start_page is not None
            and self.end_page is not None
            and self.end_page < self.start_page
        ):
            raise ValueError("end_page cannot precede start_page")
        if self.parent_section_id == self.section_id:
            raise ValueError("a textbook section cannot parent itself")
        return self


class Topic1TextbookMappingV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.textbook-mapping.v1"] = "topic1.textbook-mapping.v1"
    mapping_id: Topic1EntityId
    kp_id: KnowledgePointId
    section_id: Topic1EntityId
    mapping_type: TextbookMappingType
    coverage: float = Field(ge=0, le=1)
    note: str | None = Field(default=None, max_length=2000)
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Topic1GoldenQuestionV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.golden-question.v1"] = "topic1.golden-question.v1"
    question_id: Topic1EntityId
    primary_kp_id: KnowledgePointId
    related_kp_ids: list[KnowledgePointId] = Field(default_factory=list, max_length=32)
    question_type: GoldenQuestionType
    stem_markdown: str = Field(min_length=1, max_length=20000)
    answer_document: dict[str, Any]
    solution_markdown: str = Field(min_length=1, max_length=30000)
    difficulty_level: int = Field(ge=1, le=5)
    discrimination: float = Field(ge=0, le=1)
    diagnostic_tags: list[str] = Field(min_length=1, max_length=64)
    misconception_ids: list[Topic1EntityId] = Field(default_factory=list, max_length=32)
    authority_sources: list[AuthoritySourceRefV1] = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Topic1GraphContentV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    course: Topic1CourseV1
    knowledge_points: list[Topic1KnowledgePointV1] = Field(max_length=5000)
    prerequisites: list[Topic1PrerequisiteV1] = Field(max_length=20000)
    misconceptions: list[Topic1MisconceptionV1] = Field(default_factory=list, max_length=10000)
    textbooks: list[Topic1TextbookV1] = Field(default_factory=list, max_length=512)
    textbook_sections: list[Topic1TextbookSectionV1] = Field(
        default_factory=list,
        max_length=10000,
    )
    textbook_mappings: list[Topic1TextbookMappingV1] = Field(
        default_factory=list,
        max_length=20000,
    )
    golden_questions: list[Topic1GoldenQuestionV1] = Field(
        default_factory=list,
        max_length=20000,
    )

    @model_validator(mode="after")
    def validate_references(self) -> Topic1GraphContentV1:
        kp_ids = self._unique_ids(
            [item.kp_id for item in self.knowledge_points],
            "knowledge point",
        )
        if any(item.course_id != self.course.course_id for item in self.knowledge_points):
            raise ValueError("all knowledge points must belong to the graph course")
        self._unique_ids([item.edge_id for item in self.prerequisites], "prerequisite")
        self._ensure_unique(
            [
                (
                    item.prerequisite_kp_id,
                    item.dependent_kp_id,
                    item.relation_type,
                )
                for item in self.prerequisites
            ],
            "prerequisite relation",
        )
        for edge in self.prerequisites:
            if edge.course_id != self.course.course_id:
                raise ValueError("all prerequisites must belong to the graph course")
            if edge.prerequisite_kp_id not in kp_ids or edge.dependent_kp_id not in kp_ids:
                raise ValueError("prerequisite endpoints must exist in the graph")
        misconception_ids = self._unique_ids(
            [item.misconception_id for item in self.misconceptions],
            "misconception",
        )
        if any(item.kp_id not in kp_ids for item in self.misconceptions):
            raise ValueError("misconceptions must reference graph knowledge points")
        textbook_ids = self._unique_ids(
            [item.textbook_id for item in self.textbooks],
            "textbook",
        )
        section_ids = self._unique_ids(
            [item.section_id for item in self.textbook_sections],
            "textbook section",
        )
        if any(item.textbook_id not in textbook_ids for item in self.textbook_sections):
            raise ValueError("textbook sections must reference graph textbooks")
        self._validate_section_hierarchy(self.textbook_sections, section_ids)
        self._unique_ids([item.mapping_id for item in self.textbook_mappings], "textbook mapping")
        self._ensure_unique(
            [(item.kp_id, item.section_id, item.mapping_type) for item in self.textbook_mappings],
            "textbook mapping relation",
        )
        for mapping in self.textbook_mappings:
            if mapping.kp_id not in kp_ids or mapping.section_id not in section_ids:
                raise ValueError("textbook mappings must reference graph entities")
        self._validate_reconstructable_textbook_graph(
            self.textbooks,
            self.textbook_sections,
            self.textbook_mappings,
        )
        self._unique_ids([item.question_id for item in self.golden_questions], "golden question")
        for question in self.golden_questions:
            self._ensure_unique(question.related_kp_ids, "golden question related knowledge point")
            self._ensure_unique(question.misconception_ids, "golden question misconception")
            referenced = {question.primary_kp_id, *question.related_kp_ids}
            if not referenced <= kp_ids:
                raise ValueError("golden questions must reference graph knowledge points")
            if not set(question.misconception_ids) <= misconception_ids:
                raise ValueError("golden questions reference unknown misconceptions")
        return self

    @staticmethod
    def _unique_ids(values: list[str], label: str) -> set[str]:
        unique = set(values)
        if len(unique) != len(values):
            raise ValueError(f"duplicate {label} identity")
        return unique

    @staticmethod
    def _ensure_unique(values: list[Hashable], label: str) -> None:
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate {label}")

    @staticmethod
    def _validate_section_hierarchy(
        sections: list[Topic1TextbookSectionV1],
        section_ids: set[str],
    ) -> None:
        parents = {item.section_id: item.parent_section_id for item in sections}
        textbooks = {item.section_id: item.textbook_id for item in sections}
        if any(parent is not None and parent not in section_ids for parent in parents.values()):
            raise ValueError("textbook section parent must exist in the graph")
        if any(
            parent is not None and textbooks[parent] != textbooks[section_id]
            for section_id, parent in parents.items()
        ):
            raise ValueError("textbook section parent must belong to the same textbook")

        state: dict[str, int] = {}
        for section_id in sorted(section_ids):
            current: str | None = section_id
            trail: list[str] = []
            while current is not None and state.get(current, 0) == 0:
                state[current] = 1
                trail.append(current)
                current = parents[current]
            if current is not None and state.get(current) == 1:
                raise ValueError("textbook section hierarchy contains a cycle")
            for visited in trail:
                state[visited] = 2

    @staticmethod
    def _validate_reconstructable_textbook_graph(
        textbooks: list[Topic1TextbookV1],
        sections: list[Topic1TextbookSectionV1],
        mappings: list[Topic1TextbookMappingV1],
    ) -> None:
        parents = {item.section_id: item.parent_section_id for item in sections}
        reachable = {item.section_id for item in mappings}
        pending = list(reachable)
        while pending:
            parent = parents[pending.pop()]
            if parent is not None and parent not in reachable:
                reachable.add(parent)
                pending.append(parent)
        if reachable != set(parents):
            raise ValueError(
                "all textbook sections must be reachable from a knowledge-point mapping"
            )
        referenced_textbooks = {item.textbook_id for item in sections}
        if referenced_textbooks != {item.textbook_id for item in textbooks}:
            raise ValueError("all textbooks must contain a mapped or ancestor section")


class Topic1ImportBundleV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.import-bundle.v1"] = "topic1.import-bundle.v1"
    import_id: UUID
    expected_parent_version: int | None = Field(default=None, ge=1)
    content: Topic1GraphContentV1
    requested_at: AwareDatetime


class Topic1GraphSnapshotV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.graph-snapshot.v1"] = "topic1.graph-snapshot.v1"
    snapshot_id: UUID
    course_id: CourseId
    graph_version: int = Field(ge=1)
    parent_snapshot_id: UUID | None = None
    restored_from_snapshot_id: UUID | None = None
    content: Topic1GraphContentV1
    content_sha256: Sha256Hex
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    created_by_subject: str = Field(min_length=1, max_length=256)
    frozen_at: AwareDatetime

    @model_validator(mode="after")
    def validate_snapshot_counts(self) -> Topic1GraphSnapshotV1:
        if self.course_id != self.content.course.course_id:
            raise ValueError("snapshot course_id must match the content course")
        if self.node_count != len(self.content.knowledge_points):
            raise ValueError("snapshot node_count does not match knowledge_points")
        if self.edge_count != len(self.content.prerequisites):
            raise ValueError("snapshot edge_count does not match prerequisites")
        if self.content_sha256 != canonical_sha256(self.content.model_dump(mode="json")):
            raise ValueError("snapshot content_sha256 does not match content")
        return self


class Topic1ApiEnvelopeV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    schema_version: Literal["topic1.api-envelope.v1"] = "topic1.api-envelope.v1"
    request_id: UUID
    trace_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-fA-F0-9]+$")
    data: dict[str, Any]
