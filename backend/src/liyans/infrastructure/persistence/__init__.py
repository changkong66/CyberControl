"""Persistence ports for production adapters."""

from .outbox import OutboxMessage, OutboxRepository

__all__ = ["OutboxMessage", "OutboxRepository"]
