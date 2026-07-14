from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from liyans import __version__
from liyans.api.errors import install_exception_handlers
from liyans.api.middleware import AuthenticationTenantMiddleware
from liyans.api.routes.health import router as health_router
from liyans.api.routes.metrics import router as metrics_router
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
from liyans.infrastructure.messaging.postgres_idempotency import PostgresIdempotencyStore
from liyans.infrastructure.observability.audit import AuditService
from liyans.infrastructure.observability.logging import configure_json_logging
from liyans.infrastructure.observability.metrics import HTTPMetricsMiddleware, PlatformMetrics
from liyans.infrastructure.observability.postgres_audit import PostgresAuditStore
from liyans.infrastructure.persistence import (
    ArtifactService,
    FileSystemArtifactObjectStore,
    MessageBusOutboxSink,
    OutboxPublisher,
    PostgresArtifactRepository,
    PostgresOutboxDispatcherRepository,
    PostgresOutboxRepository,
)
from liyans.infrastructure.security import PostgresTenantAuthorizer, build_token_verifier
from liyans.infrastructure.streaming.postgres_notifications import (
    PostgresSSENotificationBridge,
)
from liyans.infrastructure.streaming.postgres_replay import PostgresSSEReplayLog
from liyans.infrastructure.streaming.sse import ReplayCursorCodec, SSEBroker
from liyans.infrastructure.tasks.queue import AsyncTaskQueue


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    metrics: PlatformMetrics = app.state.metrics
    async with AsyncExitStack() as resources:
        database = DatabaseSessionManager(create_database_engine(settings))
        resources.push_async_callback(database.close)
        app.state.database = database
        app.state.database_health = DatabaseHealthProbe(
            database.engine,
            timeout_seconds=settings.database_health_timeout_seconds,
        )
        token_verifier = build_token_verifier(settings)
        resources.push_async_callback(token_verifier.close)
        await token_verifier.initialize()
        app.state.token_verifier = token_verifier
        app.state.tenant_authorizer = PostgresTenantAuthorizer(database)
        app.state.auth_configured = settings.oidc_configured
        audit = AuditService(PostgresAuditStore(database))
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

        message_bus = AsyncMessageBus(
            idempotency_store=PostgresIdempotencyStore(
                database,
                instance_id=settings.service_instance_id,
                retention_seconds=settings.idempotency_retention_seconds,
                processing_lease_seconds=settings.idempotency_processing_lease_seconds,
            )
        )
        resources.push_async_callback(message_bus.close)
        app.state.message_bus = message_bus
        app.state.outbox = PostgresOutboxRepository(
            database,
            claim_lease_seconds=settings.outbox_claim_lease_seconds,
        )
        app.state.artifact_service = ArtifactService(
            database,
            PostgresArtifactRepository(database),
            FileSystemArtifactObjectStore(
                settings.artifact_root,
                max_object_bytes=settings.artifact_max_object_bytes,
            ),
            outbox=app.state.outbox,
        )
        app.state.outbox_publisher = None
        if settings.outbox_publisher_enabled:
            dispatcher_database = DatabaseSessionManager(
                create_database_engine(
                    settings,
                    database_url=settings.outbox_dispatcher_database_url,
                    application_name="liyans-outbox-dispatcher",
                )
            )
            resources.push_async_callback(dispatcher_database.close)
            dispatcher_repository = PostgresOutboxDispatcherRepository(
                dispatcher_database,
                claim_lease_seconds=settings.outbox_claim_lease_seconds,
            )
            publisher = OutboxPublisher(
                dispatcher_repository,
                MessageBusOutboxSink(message_bus, dispatcher_repository),
                worker_id=settings.service_instance_id,
                batch_size=settings.outbox_publisher_batch_size,
                poll_interval_seconds=settings.outbox_publisher_poll_seconds,
                retry_base_seconds=settings.outbox_publisher_retry_base_seconds,
                retry_max_seconds=settings.outbox_publisher_retry_max_seconds,
                metrics=metrics,
            )
            await publisher.start()
            resources.push_async_callback(publisher.close)
            app.state.outbox_publisher = publisher
        task_queue = AsyncTaskQueue(worker_count=settings.task_worker_count)
        await task_queue.start()
        resources.push_async_callback(task_queue.close)
        app.state.task_queue = task_queue
        replay_log = PostgresSSEReplayLog(
            database,
            retention_seconds=settings.sse_event_retention_seconds,
            max_event_bytes=settings.sse_event_max_bytes,
            max_replay_events=settings.sse_replay_capacity,
        )
        app.state.sse_broker = SSEBroker(
            replay_log,
            subscriber_queue_size=settings.sse_subscriber_queue_size,
            metrics=metrics,
        )
        app.state.sse_notification_bridge = None
        if settings.sse_notification_enabled:
            bridge = PostgresSSENotificationBridge(
                settings.sse_notification_database_url or settings.database_url,
                app.state.sse_broker,
                queue_size=settings.sse_notification_queue_size,
                reconnect_base_seconds=(settings.sse_notification_reconnect_base_seconds),
                reconnect_max_seconds=settings.sse_notification_reconnect_max_seconds,
                startup_timeout_seconds=(settings.sse_notification_startup_timeout_seconds),
                metrics=metrics,
            )
            await bridge.start()
            resources.push_async_callback(bridge.close)
            app.state.sse_notification_bridge = bridge
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
    metrics = PlatformMetrics()
    application.state.metrics = metrics
    application.add_middleware(AuthenticationTenantMiddleware)
    application.add_middleware(HTTPMetricsMiddleware, metrics=metrics)
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(metrics_router)
    application.include_router(topic3_router)
    return application


app = create_app()
