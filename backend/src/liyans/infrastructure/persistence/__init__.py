"""Persistence ports for production adapters."""

from .artifact_service import ArtifactService
from .artifacts import (
    ArtifactObjectStore,
    ArtifactRegistration,
    ArtifactRepository,
    StoredArtifactObject,
)
from .filesystem_artifacts import FileSystemArtifactObjectStore
from .outbox import OutboxDispatchRepository, OutboxMessage, OutboxRepository
from .outbox_publisher import MessageBusOutboxSink, OutboxPublisher
from .postgres_artifacts import PostgresArtifactRepository
from .postgres_outbox import PostgresOutboxRepository
from .postgres_outbox_dispatcher import PostgresOutboxDispatcherRepository

__all__ = [
    "ArtifactObjectStore",
    "ArtifactRegistration",
    "ArtifactRepository",
    "ArtifactService",
    "FileSystemArtifactObjectStore",
    "MessageBusOutboxSink",
    "OutboxDispatchRepository",
    "OutboxMessage",
    "OutboxPublisher",
    "OutboxRepository",
    "PostgresArtifactRepository",
    "PostgresOutboxDispatcherRepository",
    "PostgresOutboxRepository",
    "StoredArtifactObject",
]
