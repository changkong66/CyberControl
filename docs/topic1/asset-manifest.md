# Topic 1 交付资产清单

## 契约与数据

- `packages/contracts-python/src/liyans_contracts/topic1.py`
- `schemas/topic1.*.schema.json`
- `packages/contracts-ts/src/generated/contracts.ts`
- `packages/contracts-go/contracts/contracts.go`
- `config/contract-catalog.json`
- `data/topic1/automatic-control-principles.v1.json`

## 后端源码

- `backend/src/liyans/domains/topic1/models.py`
- `backend/src/liyans/domains/topic1/repository.py`
- `backend/src/liyans/domains/topic1/postgres_repository.py`
- `backend/src/liyans/domains/topic1/topology.py`
- `backend/src/liyans/domains/topic1/service.py`
- `backend/src/liyans/api/routes/topic1.py`
- `backend/src/liyans/api/topic1_limits.py`
- `backend/src/liyans/providers/topic1.py`
- `backend/migrations/versions/20260715_0004_create_topic_1_knowledge_topology.py`

## 自动化测试

- `backend/tests/test_topic1_api.py`
- `backend/tests/test_topic1_limits.py`
- `backend/tests/test_topic1_topology.py`
- `backend/tests/test_topic1_performance.py`
- `backend/tests/test_topic1_provider.py`
- `backend/tests/test_topic1_seed_data.py`
- `backend/tests/integration/test_postgres_topic1.py`
- `packages/contracts-python/tests/test_topic1_contracts.py`

## 工程文档与脚本

- `docs/topic1/architecture.md`
- `docs/topic1/api-examples.md`
- `docs/topic1/acceptance-report.md`
- `docs/topic1/acceptance-status.json`
- `docs/topic1/topic2-unlock.md`
- `tools/windows/run-topic1-acceptance.ps1`
