"""C8 immutable revision coordination boundary."""

from .engine import (
    ReverificationCommand,
    RevisionConflictError,
    RevisionEngine,
    RevisionError,
    RevisionIntegrityError,
    RevisionLimitError,
    RevisionOutcome,
)
from .models import TOPIC4_REVISION_TABLES
from .postgres_repository import PostgresRevisionRepository

__all__ = [
    "TOPIC4_REVISION_TABLES",
    "PostgresRevisionRepository",
    "ReverificationCommand",
    "RevisionConflictError",
    "RevisionEngine",
    "RevisionError",
    "RevisionIntegrityError",
    "RevisionLimitError",
    "RevisionOutcome",
]
