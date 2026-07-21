from __future__ import annotations

from liyans.infrastructure.messaging.bus import AsyncMessageBus, MessageHandler

IDENTITY_OUTBOX_EVENT_TYPES = (
    "identity.verification-challenge.sent",
    "identity.verification-challenge.verified",
    "identity.account.registered",
    "identity.account.compensated",
    "identity.account.reconciliation-required",
    "identity.account.projected",
    "identity.account.profile-updated",
    "identity.account.contact-changed",
    "identity.account.status-changed",
)


def register_identity_outbox_handlers(
    message_bus: AsyncMessageBus,
    handler: MessageHandler,
) -> None:
    for event_type in IDENTITY_OUTBOX_EVENT_TYPES:
        message_bus.register(event_type, handler)
