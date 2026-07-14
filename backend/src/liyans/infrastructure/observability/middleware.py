from __future__ import annotations

from collections.abc import Awaitable, Callable

from liyans_contracts.envelope import Topic3EnvelopeV1

from liyans.infrastructure.observability.audit import AuditService


class AuditMessageMiddleware:
    def __init__(self, audit: AuditService) -> None:
        self._audit = audit

    async def __call__(
        self,
        envelope: Topic3EnvelopeV1,
        call_next: Callable[[Topic3EnvelopeV1], Awaitable[None]],
    ) -> None:
        try:
            await call_next(envelope)
        except Exception as exc:
            await self._audit.record(
                tenant_id=envelope.tenant_id,
                category="MESSAGING",
                action="MESSAGE_DISPATCH",
                outcome="FAILED",
                actor_ref=envelope.subject_ref,
                target_ref=envelope.event_type,
                trace_id=envelope.trace_id,
                envelope_id=str(envelope.envelope_id),
                metadata={"exception_type": type(exc).__name__},
            )
            raise
        await self._audit.record(
            tenant_id=envelope.tenant_id,
            category="MESSAGING",
            action="MESSAGE_DISPATCH",
            outcome="SUCCEEDED",
            actor_ref=envelope.subject_ref,
            target_ref=envelope.event_type,
            trace_id=envelope.trace_id,
            envelope_id=str(envelope.envelope_id),
        )
