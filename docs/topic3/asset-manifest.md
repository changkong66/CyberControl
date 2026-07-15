# Topic 3 交付资产清单

## 1. 数据库与领域实现

- `backend/migrations/versions/20260716_0006_create_topic_3_agent_cluster_runtime.py`
- `backend/src/liyans/domains/topic3/models.py`
- `backend/src/liyans/domains/topic3/entities.py`
- `backend/src/liyans/domains/topic3/repository.py`
- `backend/src/liyans/domains/topic3/postgres_repository.py`
- `backend/src/liyans/domains/topic3/service.py`
- `backend/src/liyans/domains/topic3/blueprint.py`
- `backend/src/liyans/domains/topic3/orchestrator.py`
- `backend/src/liyans/domains/topic3/outbox.py`
- `backend/src/liyans/domains/topic3/streaming.py`

## 2. 五大 Agent 与 Provider

- `backend/src/liyans/domains/topic3/agents/base.py`
- `backend/src/liyans/domains/topic3/agents/prompts.py`
- `backend/src/liyans/domains/topic3/agents/lecturer.py`
- `backend/src/liyans/domains/topic3/agents/mindmap.py`
- `backend/src/liyans/domains/topic3/agents/tester.py`
- `backend/src/liyans/domains/topic3/agents/code_sandbox.py`
- `backend/src/liyans/domains/topic3/agents/extension.py`
- `backend/src/liyans/domains/topic3/agents/registry.py`
- `backend/src/liyans/providers/topic3.py`

## 3. API 与运行时接线

- `backend/src/liyans/api/routes/topic3.py`
- `backend/src/liyans/main.py`
- `backend/src/liyans/core/settings.py`
- `backend/src/liyans/core/errors.py`
- `.env.example`
- `config/providers.toml`

## 4. 四端契约

- `packages/contracts-python/src/liyans_contracts/topic3.py`
- `packages/contracts-python/src/liyans_contracts/registry.py`
- `schemas/topic3.*.schema.json`
- `schemas/registry.json`
- `packages/contracts-ts/src/generated/contracts.ts`
- `packages/contracts-go/contracts/contracts.go`
- `config/contract-catalog.json`

Topic 3 新增 10 个业务契约：generation command、execution blueprint、task snapshot、generation session/result，以及五类 Agent 内容契约。公共 Envelope/Block/Candidate/SSE chunk v1 语义保持不变。

## 5. 自动化测试

- `backend/tests/test_topic3_runtime.py`
- `backend/tests/test_topic3_provider.py`
- `backend/tests/test_topic3_contract_extensions.py`
- `backend/tests/test_topic3_orchestrator.py`
- `backend/tests/test_topic3_outbox.py`
- `backend/tests/test_topic3_service.py`
- `backend/tests/test_topic3_api.py`
- `backend/tests/test_topic3_performance.py`
- `backend/tests/integration/test_postgres_topic3.py`
- `backend/tests/topic3_support.py`

## 6. 工程脚本与文档

- `tools/windows/run-topic3-acceptance.ps1`
- `tools/windows/run-quality-gates.ps1`
- `.github/workflows/quality-gates.yml`
- `docs/topic3/architecture.md`
- `docs/topic3/api-examples.md`
- `docs/topic3/asset-manifest.md`
- `docs/topic3/acceptance-report.md`
- `docs/topic3/acceptance-status.json`
- `docs/topic3/topic4-unlock.md`

## 7. 生成证据目录

- `artifacts/quality-gates/`
- `artifacts/coverage/`
- `artifacts/test-results/`
- `artifacts/sbom/`
- `artifacts/security/`

证据目录由本地或 CI 重建，不作为手工维护的业务源码。
