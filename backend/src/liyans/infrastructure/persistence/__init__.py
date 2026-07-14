"""Persistence ports for production adapters."""

from .outbox import OutboxMessage, OutboxRepository
from .postgres_outbox import PostgresOutboxRepository

__all__ = ["OutboxMessage", "OutboxRepository", "PostgresOutboxRepository"]
