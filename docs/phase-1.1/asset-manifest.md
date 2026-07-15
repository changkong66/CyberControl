# Phase 1.1 冻结资产清单

## 1. 数据库与迁移

- `backend/migrations/versions/20260714_0001_phase_1_1_foundation.py`
- `backend/migrations/versions/20260714_0002_seed_platform_tenant.py`
- `backend/migrations/versions/20260715_0003_dispatch_and_sse_signal.py`
- `infra/postgres/init/001-runtime-role.sql`
- `backend/src/liyans/infrastructure/database/`

## 2. 身份、租户与审计

- `backend/src/liyans/api/middleware.py`
- `backend/src/liyans/infrastructure/security/authentication.py`
- `backend/src/liyans/infrastructure/security/tenant_authorization.py`
- `backend/src/liyans/infrastructure/observability/audit.py`
- `backend/src/liyans/infrastructure/observability/postgres_audit.py`
- `backend/src/liyans/infrastructure/observability/metrics.py`

## 3. 持久化与消息可靠性

- `backend/src/liyans/infrastructure/persistence/artifacts.py`
- `backend/src/liyans/infrastructure/persistence/artifact_service.py`
- `backend/src/liyans/infrastructure/persistence/filesystem_artifacts.py`
- `backend/src/liyans/infrastructure/persistence/postgres_artifacts.py`
- `backend/src/liyans/infrastructure/persistence/outbox.py`
- `backend/src/liyans/infrastructure/persistence/postgres_outbox.py`
- `backend/src/liyans/infrastructure/persistence/postgres_outbox_dispatcher.py`
- `backend/src/liyans/infrastructure/persistence/outbox_publisher.py`
- `backend/src/liyans/infrastructure/messaging/`

## 4. SSE 持久化与多实例同步

- `backend/src/liyans/infrastructure/streaming/sse.py`
- `backend/src/liyans/infrastructure/streaming/postgres_replay.py`
- `backend/src/liyans/infrastructure/streaming/postgres_notifications.py`
- `backend/src/liyans/api/routes/topic3.py`

## 5. CI/CD 与供应链

- `.github/workflows/quality-gates.yml`
- `.github/dependabot.yml`
- `.github/pull_request_template.md`
- `.gitleaks.toml`
- `.dockerignore`
- `infra/backend.Dockerfile`
- `infra/docker-compose.yml`
- `tools/windows/run-quality-gates.ps1`
- `tools/windows/build-go-contracts.ps1`
- `tools/generate_node_sbom.py`
- `tools/validate_sbom_policy.py`
- `tools/github/configure-repository-protection.ps1`
- `tools/github/test-repository-protection.ps1`
- `tools/github/configure-public-repository-security.ps1`
- `tools/github/verify-remote-quality-gate.ps1`
- `tools/github/set-gh-token.ps1`
- `tools/validate_commit_messages.py`
- `tools/windows/start-local.ps1`
- `tools/windows/stop-local.ps1`
- `tools/windows/invoke-public-security-audit.ps1`
- `docs/engineering/repository-governance.md`
- `docs/engineering/windows-environment-reproduction.md`
- `docs/phase-1.1/remote-acceptance-report.md`
- `docs/phase-1.1/topic1-unlock.md`
- `docs/security/public-repository-security-audit.md`

## 6. 核心自动化测试

- `backend/tests/integration/test_postgres_transactions.py`
- `backend/tests/integration/test_postgres_security.py`
- `backend/tests/integration/test_postgres_recovery.py`
- `backend/tests/integration/test_postgres_artifacts.py`
- `backend/tests/integration/test_postgres_outbox_dispatch.py`
- `backend/tests/integration/test_postgres_sse_notifications.py`
- `backend/tests/test_artifact_persistence.py`
- `backend/tests/test_messaging.py`
- `backend/tests/test_streaming.py`
- `backend/tests/test_outbox_publisher.py`
- `backend/tests/test_metrics.py`
- `backend/tests/test_performance_smoke.py`
- `backend/tests/test_node_sbom_generator.py`
- `backend/tests/test_sbom_license_policy.py`

## 7. 证据输出位置

下列目录被 Git 忽略，仅保存机器生成证据：

- `artifacts/test-results/`
- `artifacts/coverage/`
- `artifacts/sbom/`
- `artifacts/security/`
- `artifacts/container/`
- `artifacts/quality-gates/`
- `artifacts/toolchain/`

正式 release 必须将对应 commit 的证据复制到受控发布台账，不能只依赖本机文件。
