# Topic 2 阶段验收报告

## 1. 当前结论

Topic 2 数据库、仓储、六维画像、艾宾浩斯记忆、自适应路径、REST API、四端契约、测试和工程脚本已经编码完成。完整本地 Release quality redline 已通过，当前状态为 `LOCAL_ACCEPTED_REMOTE_PENDING`，尚不是最终 `ACCEPTED`。

已通过的定向证据：

| 门禁 | 当前结果 |
|---|---|
| Python 全量测试 | `195 passed, 1 skipped` |
| 全项目覆盖率 | `89.14%`，红线 `>=88%` |
| Topic 2 PostgreSQL 集成测试 | `10 passed` |
| Ruff lint/format | 0 findings / 0 drift |
| Alembic 往返与 model drift | 通过 / 无漂移 |
| Go vet/race/test/build | 通过 |
| TypeScript/Vue typecheck/build | 通过 |
| Python/Node 依赖审计与 SBOM | 通过 |
| Trivy 全等级漏洞 | 0 |
| Gitleaks 历史与工作树 | 0 |
| 完整 Release quality redline | `passed`，`2026-07-15T16:48:07.0351760Z` |
| 远端分支、PR、main CI | 待执行 |
| Topic 3 | `LOCKED` |

只有完整本地门禁、远端受保护 PR 和 main 合并 CI 全部成功后，才允许把状态改为 `ACCEPTED` 并签发 Topic 3 解锁凭证。

## 2. 功能资产验收

### 2.1 数据库与租户安全

- 六张 Topic 2 表全部只追加并启用 FORCE RLS。
- 画像、记忆、路径均使用租户/学习者/课程复合边界。
- Topic 1 课程、知识点和图谱快照使用强外键绑定。
- 行为接收游标索引支持乱序事件增量消费。
- 迁移支持 `0004 -> 0005 -> 0004 -> 0005`，最终门禁将再次验证 model drift。

### 2.2 事务一致性

- 所有写操作使用异步 `SERIALIZABLE` 事务和最多 3 次序列化重试。
- 幂等、领域快照、审计哈希链和 Outbox 在同一事务提交。
- 空白学习状态初始化把画像和全部记忆状态原子提交。
- 外键失败、版本冲突和批量异常不会留下部分画像、审计或消息。

### 2.3 六维画像

- 答题、浏览、仿真、复习、代码和专注事件自动提取特征。
- 使用 30 天证据半衰期、90 天先验半衰期和 MAD 异常过滤。
- 画像按 `(received_at, event_id)` 增量推进，支持迟到行为。
- 输出 aggregate、知识点掌握和易错点证据，并绑定 Topic 1 图谱版本。

### 2.4 记忆衰退

- 实现 `R(t)=exp(-t/S_eff)` 和难度/个体遗忘率修正。
- 成功/失败复习分别执行稳定度强化或 lapse 收缩。
- 复习事件接收游标防止重复消费，迟到事件保留原始与修正时间。
- 提供租户级到期刷新调度入口和分区幂等重试。

### 2.5 自适应路径

- 使用 Topic 1 先修图、画像和记忆状态生成路径。
- 七项评分权重总和强制为 1，决策文档完整留存。
- 支持基础、巩固、拓展三层路径和人工顺序约束。
- 对悬空边、循环和断层执行确定性修复并记录原因。

### 2.6 API 与 Agent 上下文

- 所有成功响应使用冻结 `topic3.envelope.v1`。
- OIDC scope 与领域学习者边界双重授权。
- operation ID 派生稳定资源 ID，支持进程级重试。
- `topic2.agent-context.v1` 绑定画像、记忆和路径精确版本及摘要。

## 3. 最终验收红线

以下条件缺一不可：

1. 全量 Python 单元、集成、算法和安全测试 100% 通过。
2. 全项目覆盖率 `>=88%`。
3. Ruff lint/format 零违规。
4. Alembic 全升级、全降级、单头和 model drift 通过。
5. Go fmt/vet/race/test/build 与 TypeScript/Vue 构建通过。
6. Python/Node 依赖审计、SBOM 和许可证策略通过。
7. Trivy 全等级漏洞 0，Gitleaks 历史与工作树 0。
8. 受保护分支 CI、PR CI 和 main 合并 CI 全绿。
9. `acceptance-status.json` 记录远端 commit、PR 和 Run ID。

## 4. 冻结判定

当前已经达到本地冻结候选标准，但远端验收前不得签发最终冻结。最终 `ACCEPTED` 后，以下资产只允许兼容式扩展：

- 迁移 `20260715_0005` 和六张 Topic 2 表的 RLS/只追加语义；
- 12 个 Topic 2 四端契约；
- 六维画像、记忆曲线和路径权重策略的 v1 语义；
- REST 路径、scope、幂等、审计和 Outbox 事件语义；
- Topic 3 Agent Context 的版本绑定和摘要算法。
