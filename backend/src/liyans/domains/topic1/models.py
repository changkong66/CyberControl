from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from liyans.infrastructure.database.models import Base

TOPIC1_TENANT_TABLES = (
    "topic1_courses",
    "topic1_knowledge_points",
    "topic1_prerequisites",
    "topic1_misconceptions",
    "topic1_textbooks",
    "topic1_textbook_sections",
    "topic1_textbook_mappings",
    "topic1_golden_questions",
    "topic1_graph_snapshots",
)


class Topic1CourseModel(Base):
    __tablename__ = "topic1_courses"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "course_id"),
        UniqueConstraint("tenant_id", "course_code"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("credit_hours >= 0 AND credit_hours <= 256", name="credit_hours"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')", name="status"),
        CheckConstraint(
            "jsonb_typeof(authority_sources) = 'array'",
            name="authority_sources_array",
        ),
        Index("ix_topic1_courses_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    course_code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(4000), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'zh-CN'"))
    academic_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'UNDERGRADUATE'"),
    )
    credit_hours: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    authority_sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1KnowledgePointModel(Base):
    __tablename__ = "topic1_knowledge_points"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "kp_id"),
        UniqueConstraint("tenant_id", "course_id", "kp_id"),
        ForeignKeyConstraint(
            ["tenant_id", "course_id"],
            ["topic1_courses.tenant_id", "topic1_courses.course_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("difficulty_level BETWEEN 1 AND 5", name="difficulty_level"),
        CheckConstraint("difficulty_score BETWEEN 0 AND 1", name="difficulty_score"),
        CheckConstraint("topology_level >= 0", name="topology_level"),
        CheckConstraint("topology_weight BETWEEN 0 AND 1", name="topology_weight"),
        CheckConstraint("estimated_minutes BETWEEN 1 AND 2400", name="estimated_minutes"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')", name="status"),
        CheckConstraint("jsonb_typeof(aliases) = 'array'", name="aliases_array"),
        CheckConstraint(
            "jsonb_typeof(learning_objectives) = 'array'",
            name="learning_objectives_array",
        ),
        CheckConstraint(
            "jsonb_typeof(formula_signatures) = 'array'",
            name="formula_signatures_array",
        ),
        CheckConstraint("jsonb_typeof(tags) = 'array'", name="tags_array"),
        CheckConstraint(
            "jsonb_typeof(authority_sources) = 'array'",
            name="authority_sources_array",
        ),
        Index(
            "ix_topic1_knowledge_points_course_level",
            "tenant_id",
            "course_id",
            "topology_level",
        ),
        Index(
            "ix_topic1_knowledge_points_course_difficulty",
            "tenant_id",
            "course_id",
            "difficulty_level",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    summary: Mapped[str] = mapped_column(String(4000), nullable=False)
    learning_objectives: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    difficulty_level: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_score: Mapped[float] = mapped_column(Float, nullable=False)
    topology_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    topology_weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default=text("0"),
    )
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    formula_signatures: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    authority_sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1PrerequisiteModel(Base):
    __tablename__ = "topic1_prerequisites"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "edge_id"),
        ForeignKeyConstraint(
            ["tenant_id", "course_id", "prerequisite_kp_id"],
            [
                "topic1_knowledge_points.tenant_id",
                "topic1_knowledge_points.course_id",
                "topic1_knowledge_points.kp_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "course_id", "dependent_kp_id"],
            [
                "topic1_knowledge_points.tenant_id",
                "topic1_knowledge_points.course_id",
                "topic1_knowledge_points.kp_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "course_id",
            "prerequisite_kp_id",
            "dependent_kp_id",
            "relation_type",
        ),
        CheckConstraint("prerequisite_kp_id <> dependent_kp_id", name="no_self_edge"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("strength BETWEEN 0 AND 1", name="strength"),
        CheckConstraint(
            "relation_type IN ('REQUIRED', 'RECOMMENDED', 'SUPPORTING')",
            name="relation_type",
        ),
        Index(
            "ix_topic1_prerequisites_course_dependent",
            "tenant_id",
            "course_id",
            "dependent_kp_id",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    edge_id: Mapped[str] = mapped_column(String(128), nullable=False)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prerequisite_kp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    dependent_kp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(String(2000), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1MisconceptionModel(Base):
    __tablename__ = "topic1_misconceptions"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "misconception_id"),
        ForeignKeyConstraint(
            ["tenant_id", "kp_id"],
            ["topic1_knowledge_points.tenant_id", "topic1_knowledge_points.kp_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="severity",
        ),
        CheckConstraint(
            "jsonb_typeof(diagnosis_tags) = 'array'",
            name="diagnosis_tags_array",
        ),
        Index("ix_topic1_misconceptions_kp", "tenant_id", "kp_id"),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    misconception_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(4000), nullable=False)
    trigger_pattern: Mapped[str] = mapped_column(String(2000), nullable=False)
    diagnosis_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    remediation_hint: Mapped[str] = mapped_column(String(4000), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1TextbookModel(Base):
    __tablename__ = "topic1_textbooks"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "textbook_id"),
        UniqueConstraint("tenant_id", "isbn"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("publication_year BETWEEN 1900 AND 2200", name="publication_year"),
        CheckConstraint("authority_level BETWEEN 1 AND 5", name="authority_level"),
        CheckConstraint("jsonb_typeof(authors) = 'array'", name="authors_array"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    textbook_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    authors: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False)
    edition: Mapped[str] = mapped_column(String(64), nullable=False)
    isbn: Mapped[str | None] = mapped_column(String(32))
    publication_year: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_level: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1TextbookSectionModel(Base):
    __tablename__ = "topic1_textbook_sections"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "section_id"),
        ForeignKeyConstraint(
            ["tenant_id", "textbook_id"],
            ["topic1_textbooks.tenant_id", "topic1_textbooks.textbook_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_section_id"],
            ["topic1_textbook_sections.tenant_id", "topic1_textbook_sections.section_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "start_page IS NULL OR end_page IS NULL OR end_page >= start_page",
            name="page_range",
        ),
        CheckConstraint(
            "parent_section_id IS NULL OR parent_section_id <> section_id",
            name="no_self_parent",
        ),
        Index(
            "ix_topic1_textbook_sections_textbook",
            "tenant_id",
            "textbook_id",
            "chapter_number",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    section_id: Mapped[str] = mapped_column(String(128), nullable=False)
    textbook_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_section_id: Mapped[str | None] = mapped_column(String(128))
    chapter_number: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    start_page: Mapped[int | None] = mapped_column(Integer)
    end_page: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1TextbookMappingModel(Base):
    __tablename__ = "topic1_textbook_mappings"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "mapping_id"),
        ForeignKeyConstraint(
            ["tenant_id", "kp_id"],
            ["topic1_knowledge_points.tenant_id", "topic1_knowledge_points.kp_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "section_id"],
            ["topic1_textbook_sections.tenant_id", "topic1_textbook_sections.section_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "kp_id", "section_id", "mapping_type"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("coverage BETWEEN 0 AND 1", name="coverage"),
        CheckConstraint(
            "mapping_type IN ('PRIMARY', 'SUPPORTING', 'EXAMPLE', 'EXERCISE')",
            name="mapping_type",
        ),
        Index("ix_topic1_textbook_mappings_kp", "tenant_id", "kp_id"),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mapping_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    section_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mapping_type: Mapped[str] = mapped_column(String(16), nullable=False)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(String(2000))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1GoldenQuestionModel(Base):
    __tablename__ = "topic1_golden_questions"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "question_id"),
        ForeignKeyConstraint(
            ["tenant_id", "primary_kp_id"],
            ["topic1_knowledge_points.tenant_id", "topic1_knowledge_points.kp_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("difficulty_level BETWEEN 1 AND 5", name="difficulty_level"),
        CheckConstraint("discrimination BETWEEN 0 AND 1", name="discrimination"),
        CheckConstraint(
            "question_type IN ('SINGLE_CHOICE', 'MULTIPLE_CHOICE', 'CALCULATION', "
            "'PROOF', 'DESIGN', 'SIMULATION')",
            name="question_type",
        ),
        CheckConstraint(
            "jsonb_typeof(related_kp_ids) = 'array'",
            name="related_kp_ids_array",
        ),
        CheckConstraint(
            "jsonb_typeof(answer_document) = 'object'",
            name="answer_document_object",
        ),
        CheckConstraint(
            "jsonb_typeof(diagnostic_tags) = 'array'",
            name="diagnostic_tags_array",
        ),
        CheckConstraint(
            "jsonb_typeof(misconception_ids) = 'array'",
            name="misconception_ids_array",
        ),
        CheckConstraint(
            "jsonb_typeof(authority_sources) = 'array'",
            name="authority_sources_array",
        ),
        Index(
            "ix_topic1_golden_questions_kp_difficulty",
            "tenant_id",
            "primary_kp_id",
            "difficulty_level",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    question_id: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_kp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    related_kp_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stem_markdown: Mapped[str] = mapped_column(String(20000), nullable=False)
    answer_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    solution_markdown: Mapped[str] = mapped_column(String(30000), nullable=False)
    difficulty_level: Mapped[int] = mapped_column(Integer, nullable=False)
    discrimination: Mapped[float] = mapped_column(Float, nullable=False)
    diagnostic_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    misconception_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    authority_sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Topic1GraphSnapshotModel(Base):
    __tablename__ = "topic1_graph_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "snapshot_id"),
        UniqueConstraint("tenant_id", "course_id", "graph_version"),
        ForeignKeyConstraint(
            ["tenant_id", "course_id"],
            ["topic1_courses.tenant_id", "topic1_courses.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_snapshot_id"],
            ["topic1_graph_snapshots.tenant_id", "topic1_graph_snapshots.snapshot_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "restored_from_snapshot_id"],
            ["topic1_graph_snapshots.tenant_id", "topic1_graph_snapshots.snapshot_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("graph_version >= 1", name="positive_graph_version"),
        CheckConstraint("node_count >= 0", name="nonnegative_node_count"),
        CheckConstraint("edge_count >= 0", name="nonnegative_edge_count"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint(
            "jsonb_typeof(snapshot_document) = 'object'",
            name="snapshot_document_object",
        ),
        Index(
            "ix_topic1_graph_snapshots_course_version",
            "tenant_id",
            "course_id",
            "graph_version",
        ),
    )

    snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_snapshot_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    restored_from_snapshot_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    snapshot_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
