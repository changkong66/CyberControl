from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


def topic4_record_constraints() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("version_cas >= 1", name="positive_version_cas"),
        CheckConstraint("record_sha256 ~ '^[0-9a-f]{64}$'", name="record_sha256_format"),
        CheckConstraint("immutable", name="immutable_record"),
        CheckConstraint("trace_id ~ '^[0-9a-fA-F]{16,64}$'", name="trace_id_format"),
    )


class Topic4ImmutableRecordMixin:
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version_cas: Mapped[int] = mapped_column(BigInteger, nullable=False)
    record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    audit_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_events.event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
