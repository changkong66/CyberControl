# Topic 1 开发解锁门禁说明

## 1. 解锁状态

Phase 1.1 本地与 GitHub Actions 远端验收已通过，但 GitHub Free 私有仓库无法启用
Branch Protection 或 Repository Rulesets。Topic 1 当前状态为 `LOCKED`，不得开始
业务实现。

满足以下任一外部条件并完成保护 API 回读后，才能把本文件状态改为 `UNLOCKED`：

1. 将账户/组织升级到支持私有仓库保护规则的 GitHub Pro/Team；或
2. 由项目所有者明确批准把仓库改为 Public，再应用同一保护规则。

正式解锁后的推荐开发分支：

```powershell
git switch main
git pull --ff-only origin main
git switch -c codex/topic1-knowledge-topology
```

## 2. 解锁后允许新增的边界

- 追加 Topic 1 Alembic migration，不修改既有 `20260714_0001` 至
  `20260715_0003` migration。
- 在冻结 Topic 1 Pydantic 契约上做向后兼容代码化，并生成 JSON Schema、TS 和 Go。
- 新增 `domains/topic1` 领域实体、算法、Repository protocol 和 PostgreSQL adapter。
- 复用现有 async transaction、TenantContext、FORCE RLS、Outbox、幂等和审计服务。
- 新增 Topic 1 REST API、OIDC scope 门禁、OpenAPI 和测试。
- 新增讯飞星火知识解析 Provider protocol，默认禁用且受现有白名单策略约束。

## 3. 禁止修改的冻结边界

- 不得信任客户端租户、用户或角色请求头。
- 不得改变 Phase 1.1 session/RLS 上下文、Outbox 连续分区顺序、幂等 digest 绑定和
  审计哈希链规则。
- 不得改变 Topic 3 Envelope/Block/Candidate 公共语义。
- 不得使用内存仓储替代 PostgreSQL 生产实现作为验收结果。
- 不得提前实现 Topic 2 画像路径、Topic 3 Agent 或 Topic 4 Verifier runtime。
- 不得引入讯飞星火、讯飞代码和 SeeDance 之外的业务 AI Provider。

## 4. Topic 1 入口验收

Topic 1 每个提交必须保持：

- `Release quality redline` 全绿；
- 既有 Phase 1.1 测试零回归；
- PostgreSQL RLS 跨租户隔离测试通过；
- migration upgrade/downgrade 和 model drift 为 0；
- 契约四端生成无漂移；
- 项目总体覆盖率提升并最终达到 Topic 1 要求的 `>=88%`。

当前不得创建 Topic 1 业务提交。保护生效并更新 `acceptance-status.json` 为
`ACCEPTED` 后，才执行本节开发入口；只有 Topic 1 独立验收报告状态为 `ACCEPTED`
后，才解锁 Topic 2。
