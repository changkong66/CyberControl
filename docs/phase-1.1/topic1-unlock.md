# Topic 1 开发正式解锁凭证

## 1. 解锁状态

| 属性 | 值 |
|---|---|
| Phase1.1 | `ACCEPTED` |
| Topic1 | `UNLOCKED` |
| 生效日期 | 2026-07-15 |
| 接受基线 | `611375cd8f40dfb88d418685695b5bb1a9436d7d` |
| Required status | `Release quality redline` |

仓库已切换为 Public，Classic Branch Protection、`main-release-governance`、
`immutable-release-tags`、远端 Actions 复现和公开仓库安全巡检全部通过。此前
`REMOTE_PENDING` 的唯一阻塞已经消除，允许正式开始 Topic1 自动控制原理知识拓扑编码。

## 2. 开发入口

Topic1 必须从受保护的最新 `main` 创建独立分支：

```powershell
git switch main
git pull --ff-only origin main
git switch -c codex/topic1-knowledge-topology
```

Topic1 变更禁止直接推送到 `main`。开发分支通过 `Release quality redline` 后，以 PR
方式合并。仓库当前只有所有者一个 CODEOWNER，所有者自己的 PR 无法自审；需要使用已
限定为 `pull_request` 模式的 Admin 临时 bypass，或先增加第二名可信 CODEOWNER。

## 3. 允许新增的边界

- 追加 Topic1 Alembic migration，不修改既有 `20260714_0001` 至 `20260715_0003`。
- 把冻结 Topic1 契约代码化，并生成 JSON Schema、Python、TypeScript 和 Go 定义。
- 新增 `domains/topic1` 领域实体、算法、Repository protocol 和 PostgreSQL adapter。
- 复用现有 async transaction、TenantContext、FORCE RLS、Outbox、幂等和审计服务。
- 新增 Topic1 REST API、OIDC scope 门禁、OpenAPI 和测试。
- 新增讯飞星火知识解析 Provider protocol，默认禁用并受现有白名单策略约束。

## 4. 禁止修改的冻结边界

- 不得信任客户端租户、用户或角色请求头。
- 不得改变 Phase1.1 session/RLS 上下文、Outbox 连续分区顺序、幂等 digest 绑定和审计链。
- 不得改变 Topic3 Envelope/Block/Candidate 公共语义。
- 不得以内存仓储替代 PostgreSQL 生产实现作为验收结果。
- 不得提前实现 Topic2 画像路径、Topic3 Agent 或 Topic4 Verifier runtime。
- 不得引入讯飞星火、讯飞代码和 SeeDance 之外的业务 AI Provider。

## 5. Topic1 完成门槛

- 单元、集成和安全测试 100% 通过，既有 Phase1.1 测试零回归。
- 项目总体 Python 覆盖率达到 `>=88%`。
- PostgreSQL RLS 跨租户隔离、并发写入、回滚、循环依赖和超大批量边界通过。
- Alembic upgrade/downgrade 和 model drift 为 0。
- Ruff、Go vet/race/build、TypeScript/Vue build 零违规。
- 四端契约生成无漂移，可供 Topic2 与 Topic4 直接调用。
- 独立 Topic1 验收报告状态为 `ACCEPTED` 后才可解锁 Topic2。

## 6. 解锁签发结论

Phase1.1 底层基座已正式冻结，不存在工程治理阻塞。Topic1 从本凭证生效后进入可编码
状态；Topic2 及其后续系统仍受分层门禁约束。
