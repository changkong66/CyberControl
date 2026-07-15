# Topic 2 交付资产清单

## 1. 数据库与模型

- `backend/migrations/versions/20260715_0005_create_topic_2_adaptive_learning_runtime.py`
- `backend/src/liyans/domains/topic2/models.py`
- `backend/src/liyans/domains/topic2/entities.py`
- `backend/src/liyans/domains/topic2/repository.py`
- `backend/src/liyans/domains/topic2/postgres_repository.py`

## 2. 领域算法与服务

- `backend/src/liyans/domains/topic2/profiling.py`
- `backend/src/liyans/domains/topic2/memory.py`
- `backend/src/liyans/domains/topic2/path_planning.py`
- `backend/src/liyans/domains/topic2/seed.py`
- `backend/src/liyans/domains/topic2/service.py`
- `backend/src/liyans/domains/topic2/orchestrator.py`
- `backend/src/liyans/api/routes/topic2.py`

## 3. 四端契约

- `packages/contracts-python/src/liyans_contracts/topic2.py`
- `schemas/topic2.*.schema.json`
- `packages/contracts-ts/src/generated/contracts.ts`
- `packages/contracts-go/contracts/contracts.go`
- `schemas/registry.json`
- `config/contract-catalog.json`

Topic 2 注册 12 个冻结契约：operation command、behavior command/event、profile feature/profile、memory state、path node/snapshot/change/record/generate command 和 agent context。

## 4. 自动化测试

- `backend/tests/test_topic2_algorithms.py`
- `backend/tests/test_topic2_api.py`
- `backend/tests/test_topic2_performance.py`
- `backend/tests/test_topic2_seed.py`
- `backend/tests/integration/test_postgres_topic2.py`
- `packages/contracts-python/tests/test_topic2_contracts.py`
- `backend/tests/test_database_schema.py`

## 5. Windows 工程脚本

- `tools/windows/run-topic2-acceptance.ps1`
- `tools/windows/initialize-topic2-learner.ps1`
- `tools/windows/start-topic2-local.ps1`
- `tools/windows/reset-topic2-database.ps1`
- `tools/windows/run-quality-gates.ps1`

## 6. 文档与验收台账

- `docs/topic2/architecture.md`
- `docs/topic2/api-examples.md`
- `docs/topic2/asset-manifest.md`
- `docs/topic2/acceptance-report.md`
- `docs/topic2/acceptance-status.json`
- `docs/topic2/topic3-unlock.md`

## 7. 生成证据

- `artifacts/quality-gates/windows-quality-gates.json`
- `artifacts/coverage/python-coverage.xml`
- `artifacts/test-results/`
- `artifacts/sbom/`
- `artifacts/security/`

生成证据目录由质量门禁维护，允许在 CI 中重新生成，不作为手工修改的业务资产。
