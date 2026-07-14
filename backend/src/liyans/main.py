from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from liyans import __version__
from liyans.api.errors import install_exception_handlers
from liyans.api.middleware import TenantTraceMiddleware
from liyans.api.routes.health import router as health_router
from liyans.api.routes.topic3 import router as topic3_router
from liyans.core.config import ConfigSnapshot, HotReloadingTomlConfig
from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.settings import get_settings
from liyans.infrastructure.database import (
    DatabaseHealthProbe,
    DatabaseSessionManager,
    create_database_engine,
)
from liyans.infrastructure.messaging.bus import AsyncMessageBus
from liyans.infrastructure.observability.audit import AuditService, JsonlAuditStore
from liyans.infrastructure.observability.logging import configure_json_logging
from liyans.infrastructure.streaming.sse import (
    InMemorySSEReplayLog,
    ReplayCursorCodec,
    SSEBroker,
)
from liyans.infrastructure.tasks.queue import AsyncTaskQueue


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    async with AsyncExitStack() as resources:
        database = DatabaseSessionManager(create_database_engine(settings))
        resources.push_async_callback(database.close)
        app.state.database = database
        app.state.database_health = DatabaseHealthProbe(
            database.engine,
            timeout_seconds=settings.database_health_timeout_seconds,
        )
        audit = AuditService(JsonlAuditStore(settings.audit_log_path))
        app.state.audit = audit

        provider_config = HotReloadingTomlConfig(
            settings.provider_policy_path,
            validator=ProviderPolicyRegistry.from_document,
            poll_interval_seconds=settings.provider_policy_poll_seconds,
        )

        async def apply_provider_policy(snapshot: ConfigSnapshot) -> None:
            app.state.provider_policy = ProviderPolicyRegistry.from_document(snapshot.document)

        async def audit_config_rejection(path: Path, exc: Exception) -> None:
            await audit.record(
                tenant_id="platform",
                category="CONFIG",
                action="CONFIG_RELOAD",
                outcome="REJECTED",
                actor_ref="system:config-watcher",
                target_ref=str(path),
                metadata={"exception_type": type(exc).__name__},
                critical=False,
            )

        provider_config.add_listener(apply_provider_policy)
        provider_config.add_rejection_listener(audit_config_rejection)
        await provider_config.start()
        resources.push_async_callback(provider_config.close)
        app.state.provider_config = provider_config

        message_bus = AsyncMessageBus()
        resources.push_async_callback(message_bus.close)
        app.state.message_bus = message_bus
        task_queue = AsyncTaskQueue(worker_count=settings.task_worker_count)
        await task_queue.start()
        resources.push_async_callback(task_queue.close)
        app.state.task_queue = task_queue
        replay_log = InMemorySSEReplayLog(capacity_per_tenant=settings.sse_replay_capacity)
        app.state.sse_broker = SSEBroker(
            replay_log,
            subscriber_queue_size=settings.sse_subscriber_queue_size,
        )
        app.state.sse_cursor_codec = ReplayCursorCodec(settings.sse_cursor_secret.encode("utf-8"))
        yield


def create_app() -> FastAPI:
    configure_json_logging()
    application = FastAPI(
        title="Liyan API",
        version=__version__,
        default_response_class=JSONResponse,
        lifespan=lifespan,
    )
    application.add_middleware(TenantTraceMiddleware)
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(topic3_router)
    return application


app = create_app()
