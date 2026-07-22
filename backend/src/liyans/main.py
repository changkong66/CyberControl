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
from liyans.api.routes.identity import (
    account_router as identity_account_router,
)
from liyans.api.routes.identity import (
    public_router as identity_public_router,
)
from liyans.api.routes.identity import (
    tenant_account_router as identity_tenant_account_router,
)
from liyans.api.routes.identity import (
    tenant_registration_router as identity_tenant_registration_router,
)
from liyans.api.routes.metrics import router as metrics_router
from liyans.api.routes.topic1 import router as topic1_router
from liyans.api.routes.topic2 import router as topic2_router
from liyans.api.routes.topic3 import router as topic3_router
from liyans.api.routes.topic4 import router as topic4_router
from liyans.api.topic1_limits import Topic1ImportBodyLimitMiddleware
from liyans.core.config import ConfigSnapshot, HotReloadingTomlConfig
from liyans.core.provider_policy import ProviderPolicyRegistry
from liyans.core.settings import get_settings
from liyans.domains.compliance.service import ComplianceBuilderPolicy, ComplianceEvidenceService
from liyans.domains.identity.keycloak import KeycloakAdminClient
from liyans.domains.identity.outbox import register_identity_outbox_handlers
from liyans.domains.identity.service import IdentityReconciliationWorker, IdentityService
from liyans.domains.knowledge.artifact_writer import KnowledgeArtifactWriter
from liyans.domains.knowledge.postgres_repository import PostgresKnowledgeRepository
from liyans.domains.knowledge.retrieval import HotReloadableRAGIndex
from liyans.domains.knowledge.retrieval_service import KnowledgeRetrievalService
from liyans.domains.knowledge.transactions import KnowledgeTransactionCoordinator
from liyans.domains.release.engine import C12ReleaseService
from liyans.domains.release.postgres_repository import PostgresAtomicReleaseRepository
from liyans.domains.revision.engine import RevisionEngine
from liyans.domains.revision.postgres_repository import PostgresRevisionRepository
from liyans.domains.topic1.postgres_repository import PostgresTopic1Repository
from liyans.domains.topic1.service import MAX_IMPORT_HTTP_BYTES, Topic1Service
from liyans.domains.topic2.memory import EbbinghausMemoryEngine
from liyans.domains.topic2.orchestrator import Topic2Orchestrator
from liyans.domains.topic2.path_planning import AdaptivePathPlanner
from liyans.domains.topic2.postgres_repository import PostgresTopic2Repository
from liyans.domains.topic2.profiling import SixDimensionProfileEngine
from liyans.domains.topic2.service import Topic2Service
from liyans.domains.topic3.agents import Topic3AgentRegistry
from liyans.domains.topic3.blueprint import ImmutableBlueprintPlanner
from liyans.domains.topic3.orchestrator import TOPIC3_WORKFLOW_TASK, Topic3Orchestrator
from liyans.domains.topic3.outbox import (
    DOMAIN_OUTBOX_EVENT_TYPES,
    DurableOutboxSSEBridge,
    Topic3WorkflowOutboxConsumer,
)
from liyans.domains.topic3.postgres_repository import PostgresTopic3Repository
from liyans.domains.topic3.service import Topic3Service
from liyans.domains.topic3.streaming import Topic3StreamCoordinator
from liyans.domains.verification.execution import BoundedModuleExecutor
from liyans.domains.verification.postgres_repository import PostgresVerificationRepository
from liyans.domains.verification.reporting import (
    TransactionalVerificationArtifactWriter,
    VerificationReportBuilder,
)
from liyans.domains.verification.runtime import (
    TOPIC4_INTERNAL_OUTBOX_EVENT_TYPES,
    TOPIC4_VERIFICATION_TASK,
    Topic3CandidateVerificationConsumer,
    Topic4PublicationSSEConsumer,
    Topic4Runtime,
    Topic4RuntimeMetrics,
    build_topic4_handlers,
)
from liyans.domains.verification.service import VerificationService, VerifierRuntimeVersions
from liyans.domains.verification.state_machine import VerificationStateMachine
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
from liyans.providers import build_topic3_provider_registry


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
            policy = ProviderPolicyRegistry.from_document(snapshot.document)
            app.state.provider_policy = policy
            topic3_registry = getattr(app.state, "topic3_provider_registry", None)
            if topic3_registry is not None:
                topic3_registry.update_policy(policy)

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
        keycloak_admin = None
        if settings.keycloak_admin_base_url and settings.keycloak_admin_client_secret:
            keycloak_admin = KeycloakAdminClient(
                base_url=settings.keycloak_admin_base_url,
                realm=settings.keycloak_admin_realm,
                client_id=settings.keycloak_admin_client_id,
                client_secret=settings.keycloak_admin_client_secret.get_secret_value(),
                timeout_seconds=settings.keycloak_admin_http_timeout_seconds,
                max_response_bytes=settings.keycloak_admin_max_response_bytes,
            )
        identity_reconciliation_catalog = None
        if settings.identity_reconciler_database_url:
            identity_reconciliation_catalog = DatabaseSessionManager(
                create_database_engine(
                    settings,
                    database_url=settings.identity_reconciler_database_url,
                    application_name="liyans-identity-reconciler",
                )
            )
            resources.push_async_callback(identity_reconciliation_catalog.close)
        app.state.identity_reconciliation_catalog = identity_reconciliation_catalog
        identity_service = IdentityService(
            database,
            app.state.outbox,
            settings,
            keycloak=keycloak_admin,
            instance_id=settings.service_instance_id,
            reconciliation_catalog=identity_reconciliation_catalog,
        )
        resources.push_async_callback(identity_service.close)
        identity_reconciliation_worker = IdentityReconciliationWorker(
            identity_service,
            interval_seconds=settings.registration_reconciliation_interval_seconds,
        )
        await identity_reconciliation_worker.start()
        resources.push_async_callback(identity_reconciliation_worker.close)
        app.state.identity_service = identity_service
        app.state.identity_reconciliation_worker = identity_reconciliation_worker
        topic1_repository = PostgresTopic1Repository()
        app.state.topic1_service = Topic1Service(
            database,
            topic1_repository,
            app.state.outbox,
            instance_id=settings.service_instance_id,
        )
        topic2_repository = PostgresTopic2Repository()
        app.state.topic2_service = Topic2Service(
            database,
            topic2_repository,
            topic1_repository,
            app.state.outbox,
            instance_id=settings.service_instance_id,
        )
        app.state.topic2_orchestrator = Topic2Orchestrator(
            database,
            topic1_repository,
            app.state.topic2_service,
            SixDimensionProfileEngine(),
            EbbinghausMemoryEngine(),
            AdaptivePathPlanner(),
        )
        artifact_repository = PostgresArtifactRepository(database)
        artifact_store = FileSystemArtifactObjectStore(
            settings.artifact_root,
            max_object_bytes=settings.artifact_max_object_bytes,
        )
        app.state.artifact_store = artifact_store
        app.state.artifact_service = ArtifactService(
            database,
            artifact_repository,
            artifact_store,
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
            app.state.outbox_publisher = publisher
        task_queue = AsyncTaskQueue(worker_count=settings.task_worker_count)
        app.state.task_queue = task_queue
        replay_log = PostgresSSEReplayLog(
            database,
            retention_seconds=settings.sse_event_retention_seconds,
            max_event_bytes=settings.sse_event_max_bytes,
            max_replay_events=settings.sse_replay_capacity,
        )
        app.state.sse_replay_log = replay_log
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
        topic3_provider_registry = build_topic3_provider_registry(
            settings,
            app.state.provider_policy,
        )
        resources.push_async_callback(topic3_provider_registry.close)
        app.state.topic3_provider_registry = topic3_provider_registry
        topic3_repository = PostgresTopic3Repository()
        app.state.topic3_service = Topic3Service(
            database,
            topic3_repository,
            app.state.outbox,
            instance_id=settings.service_instance_id,
        )
        app.state.topic3_orchestrator = Topic3Orchestrator(
            database,
            topic1_repository,
            app.state.topic2_orchestrator,
            app.state.topic3_service,
            ImmutableBlueprintPlanner(),
            Topic3AgentRegistry(topic3_provider_registry),
            Topic3StreamCoordinator(app.state.sse_broker),
        )

        verification_repository = PostgresVerificationRepository()
        knowledge_repository = PostgresKnowledgeRepository()
        knowledge_transactions = KnowledgeTransactionCoordinator(
            database,
            app.state.outbox,
            instance_id=settings.service_instance_id,
            build_version="topic4-c2-v1",
        )
        retrieval_service = KnowledgeRetrievalService(
            database,
            knowledge_repository,
            topic1_repository,
            KnowledgeArtifactWriter(artifact_repository, artifact_store),
            knowledge_transactions,
            HotReloadableRAGIndex(),
        )
        verification_service = VerificationService(
            database,
            verification_repository,
            topic3_repository,
            app.state.outbox,
            VerificationStateMachine(),
            VerifierRuntimeVersions(
                state_machine_version="c1-state-machine-v1",
                verifier_build_version="topic4-runtime-c3-semantic-v2",
                policy_version="topic4-policy-v1",
                prompt_bundle_version="topic4-prompts-v1",
                retrieval_pipeline_version="local-hybrid-rag-v1",
                knowledge_base_version="topic1-authority-v1",
                toolchain_manifest_version="topic4-toolchain-v1",
                content_security_policy_version="c9-content-security-policy-v1",
                license_policy_version="c11-supply-chain-policy-v1",
            ),
            instance_id=settings.service_instance_id,
            report_builder=VerificationReportBuilder(
                TransactionalVerificationArtifactWriter(
                    artifact_repository,
                    artifact_store,
                ),
                knowledge_base_version="topic1-authority-v1",
                policy_version="topic4-policy-v1",
            ),
        )
        compliance_service = ComplianceEvidenceService(
            database,
            verification_repository,
            knowledge_repository,
            artifact_store,
            app.state.outbox,
            ComplianceBuilderPolicy.load(settings.compliance_builder_policy_path),
            instance_id=settings.service_instance_id,
        )
        app.state.topic4_compliance_service = compliance_service
        topic4_metrics = Topic4RuntimeMetrics(metrics.registry)
        handlers = build_topic4_handlers(
            database=database,
            verification_service=verification_service,
            knowledge_repository=knowledge_repository,
            topic1_repository=topic1_repository,
            topic3_repository=topic3_repository,
            retrieval_service=retrieval_service,
            artifact_store=artifact_store,
            metrics=topic4_metrics,
            compliance_service=compliance_service,
        )
        release_service = C12ReleaseService(
            PostgresAtomicReleaseRepository(
                database,
                app.state.outbox,
                verification_repository,
                topic3_repository,
                instance_id=settings.service_instance_id,
            ),
            artifact_store,
        )
        topic4_runtime = Topic4Runtime(
            database,
            verification_service,
            verification_repository,
            retrieval_service,
            knowledge_repository,
            topic1_repository,
            topic3_repository,
            RevisionEngine(
                PostgresRevisionRepository(topic3_repository),
                topic3_repository,
                artifact_store,
            ),
            release_service,
            artifact_store,
            app.state.outbox,
            BoundedModuleExecutor(
                handlers,
                worker_instance_id=settings.service_instance_id,
            ),
            topic4_metrics,
            instance_id=settings.service_instance_id,
            task_queue=task_queue,
            compliance_service=compliance_service,
        )
        app.state.topic4_runtime = topic4_runtime
        app.state.topic4_verification_service = verification_service
        app.state.topic4_retrieval_service = retrieval_service
        app.state.topic4_release_service = release_service
        app.state.topic4_metrics = topic4_metrics
        task_queue.register(
            TOPIC3_WORKFLOW_TASK,
            app.state.topic3_orchestrator.handle_queue_task,
            circuit_failure_threshold=3,
        )
        task_queue.register(
            TOPIC4_VERIFICATION_TASK,
            topic4_runtime.handle_queue_task,
            circuit_failure_threshold=3,
        )
        message_bus.register(
            "topic3.workflow.created",
            Topic3WorkflowOutboxConsumer(app.state.topic3_orchestrator, task_queue),
        )
        message_bus.register(
            "topic3.workflow.finalized",
            Topic3CandidateVerificationConsumer(topic4_runtime, app.state.topic3_service),
        )
        message_bus.register(
            "topic4.publication.committed",
            Topic4PublicationSSEConsumer(app.state.sse_broker, topic4_metrics),
        )
        outbox_sse_bridge = DurableOutboxSSEBridge(app.state.sse_broker)
        register_identity_outbox_handlers(message_bus, outbox_sse_bridge)
        for event_type in DOMAIN_OUTBOX_EVENT_TYPES:
            message_bus.register(event_type, outbox_sse_bridge)
        for event_type in TOPIC4_INTERNAL_OUTBOX_EVENT_TYPES:
            message_bus.register(event_type, outbox_sse_bridge)
        await task_queue.start()
        resources.push_async_callback(task_queue.close)
        if app.state.outbox_publisher is not None:
            await app.state.outbox_publisher.start()
            resources.push_async_callback(app.state.outbox_publisher.close)
        topic4_runtime.mark_ready()
        topic4_metrics.ready.set(1)
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
    application.add_middleware(
        Topic1ImportBodyLimitMiddleware,
        max_body_bytes=MAX_IMPORT_HTTP_BYTES,
    )
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(metrics_router)
    application.include_router(identity_public_router)
    application.include_router(identity_account_router)
    application.include_router(identity_tenant_account_router)
    application.include_router(identity_tenant_registration_router)
    application.include_router(topic1_router)
    application.include_router(topic2_router)
    application.include_router(topic3_router)
    application.include_router(topic4_router)
    return application


app = create_app()
